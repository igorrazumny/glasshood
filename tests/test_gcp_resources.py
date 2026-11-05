# REQ-GHA-023: read-only checks of a monitored project's real parts, and its findings.
# Google's APIs are faked; nothing here calls the network.

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from src.collectors import gcp_resources as g
from src.collectors import manifest_metrics as mm


class _Resp:
    def __init__(self, code, body=None):
        self.status_code = code
        self._body = body or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("bad", request=None, response=self)


@pytest.fixture
def api(monkeypatch):
    """Route URLs to canned answers: {substring: _Resp or callable(params)}."""
    routes, seen = {}, []
    monkeypatch.setattr(g, "_token", lambda: "t")

    def fake_get(url, params=None):
        seen.append((url, dict(params or {})))
        for key, resp in routes.items():
            if key in url:
                return resp(params or {}) if callable(resp) else resp
        return _Resp(404)

    monkeypatch.setattr(g, "_get", fake_get)
    return routes, seen


def _iso(days):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat().replace("+00:00", "Z")


def test_certificate_status_follows_days_to_expiry(api):
    routes, _ = api
    for days, want in [(58, "healthy"), (20, "degraded"), (3, "error")]:
        routes["sslCertificates"] = _Resp(200, {"expireTime": _iso(days), "managed": {"status": "ACTIVE"}})
        r = g.probe_compute("p", "global/sslCertificates/c")
        assert r["status"] == want, days
        assert r["metrics"]["days_to_expiry"] == pytest.approx(days, abs=0.2)


def test_certificate_not_active_is_error(api):
    routes, _ = api
    routes["sslCertificates"] = _Resp(200, {"expireTime": _iso(80), "managed": {"status": "PROVISIONING"}})
    assert g.probe_compute("p", "global/sslCertificates/c")["status"] == "error"


def test_compute_state_and_fields(api):
    routes, _ = api
    routes["addresses"] = _Resp(200, {"status": "IN_USE", "address": "34.8.142.111"})
    r = g.probe_compute("p", "global/addresses/ip", ["address"])
    assert r["status"] == "healthy" and r["metrics"]["address"] == "34.8.142.111"
    routes["addresses"] = _Resp(200, {"status": "RESERVING"})
    assert g.probe_compute("p", "global/addresses/ip")["status"] == "error"


def test_compute_missing_or_refused_is_error(api):
    assert g.probe_compute("p", "global/firewalls/gone")["status"] == "error"
    api[0]["firewalls"] = _Resp(403)
    r = g.probe_compute("p", "global/firewalls/x")
    assert r["status"] == "error" and "403" in r["check_description"]


def test_mig_status_object_is_not_a_state_and_urls_shorten(api):
    api[0]["instanceGroupManagers"] = _Resp(200, {
        "targetSize": 1, "status": {"isStable": True},
        "instanceTemplate": "https://compute.googleapis.com/.../instanceTemplates/tpl-v2"})
    r = g.probe_compute("p", "zones/z/instanceGroupManagers/m", ["targetSize", "instanceTemplate", "status.isStable"])
    assert r["status"] == "healthy"
    assert r["metrics"] == {"targetSize": 1, "instanceTemplate": "tpl-v2", "isStable": True}


def test_backend_health_counts_healthy(monkeypatch, api):
    api[0]["backendServices/bs"] = _Resp(200, {"backends": [{"group": "g1"}]})
    for states, want in [(["HEALTHY"], "healthy"), (["HEALTHY", "UNHEALTHY"], "degraded"),
                         (["UNHEALTHY"], "error"), ([], "error")]:
        monkeypatch.setattr(g.httpx, "post", lambda *a, s=states, **k: _Resp(
            200, {"healthStatus": [{"healthState": x} for x in s]}))
        r = g.probe_backend_health("p", "bs")
        assert r["status"] == want, states


def test_asset_duplicates_are_drift(api):
    api[0]["searchAllResources"] = _Resp(200, {"results": [{"displayName": "A"}] * 29})
    r = g.probe_asset("p", "monitoring.googleapis.com/AlertPolicy", expect="one")
    assert r["status"] == "healthy" and r["metrics"]["count"] == 29 and r["metrics"]["duplicates"] == 28
    assert "drift" in r["check_description"]
    assert g.probe_asset("p", "monitoring.googleapis.com/AlertPolicy", expect="any")["status"] == "healthy"


def test_asset_name_must_match_exactly(api):
    api[0]["searchAllResources"] = _Resp(200, {"results": [{"displayName": "coldvault-repo-old"}]})
    assert g.probe_asset("p", "t", name="coldvault-repo")["status"] == "error"


def test_asset_pages_are_followed(api):
    pages = {None: {"results": [{"displayName": "a"}], "nextPageToken": "2"},
             "2": {"results": [{"displayName": "a"}]}}
    api[0]["searchAllResources"] = lambda params: _Resp(200, pages[params.get("pageToken")])
    assert g.probe_asset("p", "t", expect="any")["metrics"]["count"] == 2


def test_secret_count_reads_metadata_only(api):
    routes, seen = api
    routes["/secrets"] = _Resp(200, {"secrets": [{"name": f"s{i}"} for i in range(22)]})
    r = g.probe_secret_count("p")
    assert r["status"] == "healthy" and r["metrics"]["secrets"] == 22
    assert all(":access" not in url and "/versions" not in url for url, _ in seen)


def test_sql_backup_age(api):
    def backups(hours):
        t = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
        return _Resp(200, {"results": [{"state": "SUCCESSFUL", "createTime": t},
                                       {"state": "FAILED", "createTime": _iso(0)}]})
    for hours, want in [(19, "healthy"), (50, "degraded"), (80, "error")]:
        api[0]["searchAllResources"] = backups(hours)
        r = g.probe_sql_backup("p", 36)
        assert r["status"] == want and r["metrics"]["last_backup_age_h"] == pytest.approx(hours, abs=0.1)
    api[0]["searchAllResources"] = _Resp(200, {"results": [{"state": "FAILED", "createTime": _iso(0)}]})
    assert g.probe_sql_backup("p")["status"] == "error"


def test_findings_active_only_while_their_check_holds(api):
    api[0]["searchAllResources"] = lambda params: _Resp(200, {"results": [
        {"displayName": "x"}] * (29 if "AlertPolicy" in params["assetTypes"] else 0)})
    found = g.evaluate_findings("p", [
        {"id": "dup", "text": "{count} alert policies", "check": {
            "asset_type": "monitoring.googleapis.com/AlertPolicy", "min_count": 2}},
        {"id": "gone", "text": "leftover rule", "check": {
            "asset_type": "compute.googleapis.com/Firewall", "name": "x"}},
        {"id": "said", "text": "Auth0 idle", "source": "ColdVault architect"},
    ])
    assert [(f["id"], f["text"], f["checked"]) for f in found] == [
        ("dup", "29 alert policies", True), ("said", "Auth0 idle", False)]


def test_finding_whose_check_fails_is_not_reported(api):
    api[0]["searchAllResources"] = _Resp(500)
    assert g.evaluate_findings("p", [{"id": "a", "text": "t", "check": {"asset_type": "x"}}]) == []


def test_poll_node_dispatches_resource_and_external_probes(monkeypatch):
    monkeypatch.setitem(mm._RESOURCE_PROBES, "gcp_asset",
                        lambda c: {"status": "healthy", "metrics": {"count": 1}, "check_description": "ok"})
    r = mm._poll_node({"id": "n", "monitoring": {"probe": {"type": "gcp_asset"}}})
    assert r == {"node_id": "n", "status": "healthy", "metrics": {"count": 1}, "check_description": "ok"}
    r = mm._poll_node({"id": "o", "monitoring": {"probe": {"type": "external", "note": "OpenAI, Partner Mode"}}})
    assert r["status"] == "not checked" and r["check_description"] == "OpenAI, Partner Mode"


def test_with_one_vm_the_vm_carries_the_badge(monkeypatch):
    import src.collectors.coldvault_mcp as cv
    monkeypatch.setattr(mm, "_metrics_cache", {
        "vm-a": {"status": "healthy", "metrics": {}, "_parent": "mig"},
        "vm-b": {"status": "healthy", "metrics": {}, "_parent": "mig"},
        "other": {"status": "healthy", "metrics": {}},
    })
    monkeypatch.setattr(cv, "check_attestation", lambda url, t: {"ok": True, "desc": "verified", "metrics": {}})
    del mm._metrics_cache["vm-b"]  # one VM behind the endpoint: the answer can only be from it
    mm._attest_vms("mig", {"url": "u"})
    assert mm._metrics_cache["vm-a"]["metrics"]["attested"] == 1
    assert "attested" not in mm._metrics_cache["other"]["metrics"]
    monkeypatch.setattr(cv, "check_attestation", lambda url, t: {"ok": False, "desc": "not bound", "metrics": {}})
    mm._attest_vms("mig", {"url": "u"})
    assert mm._metrics_cache["vm-a"]["metrics"]["attested"] == 0
    assert mm._metrics_cache["vm-a"]["status"] == "degraded"


def test_no_retired_gpu_override():
    import yaml
    with open("config/topology_overrides.yaml") as f:
        assert yaml.safe_load(f)["nodes"] == []


def test_vm_details_read_confidential_and_shielded(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp(200, {
        "machineType": "https://x/machineTypes/n2d-standard-2",
        "confidentialInstanceConfig": {"confidentialInstanceType": "SEV_SNP"},
        "shieldedInstanceConfig": {"enableSecureBoot": True, "enableVtpm": True, "enableIntegrityMonitoring": False}}))
    assert mm._vm_details("https://x/instances/a", "t") == {
        "machine_type": "n2d-standard-2", "confidential": "SEV_SNP",
        "secure_boot": True, "vtpm": True, "integrity_monitoring": False}
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp(403))
    assert mm._vm_details("https://x/instances/a", "t") == {}


def test_asset_refusal_reports_the_http_status(api):
    api[0]["searchAllResources"] = _Resp(403)
    r = g.probe_asset("p", "t", name="x")
    assert r["status"] == "error" and r["check_description"] == "Cloud Asset Inventory HTTP 403"


def test_list_fields_keep_cidr_ranges(api):
    api[0]["firewalls"] = _Resp(200, {"sourceRanges": ["130.211.0.0/22", "35.191.0.0/16"],
                                      "targetTags": ["https://x/y/http-server"]})
    m = g.probe_compute("p", "global/firewalls/f", ["sourceRanges", "targetTags"])["metrics"]
    assert m == {"sourceRanges": "130.211.0.0/22, 35.191.0.0/16", "targetTags": "http-server"}


def test_quota_project_header_only_when_credentials_name_one(monkeypatch):
    class C:
        valid, token, quota_project_id = True, "t", None
    monkeypatch.setattr(g, "_creds", C())
    assert g._headers() == {"Authorization": "Bearer t"}
    C.quota_project_id = "qp"
    assert g._headers()["x-goog-user-project"] == "qp"


def test_asset_search_queries_the_quoted_display_name(api):
    routes, seen = api
    routes["searchAllResources"] = _Resp(200, {"results": [{"displayName": "ColdVault Error Spike"}]})
    g.probe_asset("p", "monitoring.googleapis.com/AlertPolicy", name="ColdVault Error Spike")
    assert seen[-1][1]["query"] == 'displayName:"ColdVault Error Spike"'


def test_unissued_certificate_is_not_healthy(api):
    api[0]["sslCertificates"] = _Resp(200, {"managed": {"status": "PROVISIONING"}})
    r = g.probe_compute("p", "global/sslCertificates/c")
    assert r["status"] == "error" and "PROVISIONING" in r["check_description"]


def test_backend_group_that_cannot_be_read_is_never_green(monkeypatch, api):
    api[0]["backendServices/bs"] = _Resp(200, {"backends": [{"group": "g1"}, {"group": "g2"}]})
    answers = iter([_Resp(200, {"healthStatus": [{"healthState": "HEALTHY"}]}), _Resp(503)])
    monkeypatch.setattr(g.httpx, "post", lambda *a, **k: next(answers))
    r = g.probe_backend_health("p", "bs")
    assert r["status"] == "degraded" and r["metrics"]["unread_groups"] == 1
    assert "could not be read" in r["check_description"]


def test_with_several_vms_no_vm_gets_the_badge(monkeypatch):
    import src.collectors.coldvault_mcp as cv
    monkeypatch.setattr(mm, "_metrics_cache", {
        "mig": {"status": "healthy", "metrics": {}},
        "vm-a": {"status": "healthy", "metrics": {"attested": 1}, "_parent": "mig"},
        "vm-b": {"status": "healthy", "metrics": {}, "_parent": "mig"},
    })
    monkeypatch.setattr(cv, "check_attestation", lambda url, t: {"ok": True, "desc": "verified", "metrics": {}})
    mm._attest_vms("mig", {"url": "u"})
    assert "attested" not in mm._metrics_cache["vm-a"]["metrics"]
    assert "attested" not in mm._metrics_cache["vm-b"]["metrics"]
    assert "cannot tell which VM" in mm._metrics_cache["vm-b"]["metrics"]["attestation"]
    assert mm._metrics_cache["mig"]["metrics"]["endpoint_attested"] == 1
    monkeypatch.setattr(cv, "check_attestation", lambda url, t: {"ok": False, "desc": "not bound", "metrics": {}})
    mm._attest_vms("mig", {"url": "u"})
    assert mm._metrics_cache["mig"]["status"] == "degraded"
    assert mm._metrics_cache["vm-a"]["status"] == "healthy"  # not blamed without evidence


def test_embeddings_child_stays_not_checked_through_inheritance():
    import os
    import yaml
    from src.api.routes.topology import inherit_parent_status
    path = os.path.expanduser("~/AgentCoding/neo/glasshood-deploy/coldvault.yaml.v4")
    if not os.path.exists(path):
        pytest.skip("deployment manifest not on this machine")
    env = yaml.safe_load(open(path))["environments"][0]
    tmpl = next(n for n in env["nodes"] if n["id"] == "cv-mig")["children_template"]
    kids = mm.resolve_children_template(tmpl, "v", "1")
    inherit_parent_status(kids, "healthy")
    emb = next(c for c in kids[0]["children"] if c["id"].endswith("-embeddings"))
    assert emb["status"] == "not checked"
