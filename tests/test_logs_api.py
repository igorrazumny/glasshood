# File: tests/test_logs_api.py
# Purpose: Tests for /api/logs/{node_id}.
# REQ-704: server-side filter+project resolution from node_id; attacker-supplied
# log_filter/log_project are IGNORED. Unknown node ids return a canonical error
# without ever calling GCP Cloud Logging.
# REQ-212 (retained): nodes that exist but don't declare monitoring.logs fall
# back to the project-scoped gce_instance default — never an arbitrary project.

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes.logs import router


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestLogsApi:
    def test_manifest_node_with_declared_logs_uses_manifest_values(self):
        """REQ-704: when the manifest declares monitoring.logs, query uses exactly those."""
        with patch("src.api.routes.logs.verify_token") as mock_verify, \
             patch("src.api.routes.logs._query_logs_with_filter") as mock_query, \
             patch("src.api.routes.logs._resolve_node") as mock_resolve:
            mock_verify.return_value = None
            mock_resolve.return_value = ("manifest_logs",
                                         "example-platform-project",
                                         'jsonPayload.container.name="/platform"')
            mock_query.return_value = [{"timestamp": "t", "severity": "INFO", "message": "m"}]
            r = _client().get("/api/logs/pl-api")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 1
        assert "error" not in body
        args = mock_query.call_args.args
        assert args[0] == "example-platform-project"
        assert args[1] == 'jsonPayload.container.name="/platform"'

    def test_attacker_supplied_filter_and_project_are_ignored(self):
        """REQ-704: log_filter and log_project query params do NOT influence the query.

        This is the core SSRF/IDOR fix: an authenticated demo user constructing
        ?log_filter=...&log_project=other-project must NOT be able to redirect
        the GCP call. Manifest-derived values win.
        """
        with patch("src.api.routes.logs.verify_token") as mock_verify, \
             patch("src.api.routes.logs._query_logs_with_filter") as mock_query, \
             patch("src.api.routes.logs._resolve_node") as mock_resolve, \
             patch("src.config.settings.GCP_PROJECT_ID", "trusted-project"):
            mock_verify.return_value = None
            mock_resolve.return_value = ("manifest_logs",
                                         "trusted-project",
                                         'resource.type="gce_instance"')
            mock_query.return_value = []
            r = _client().get(
                "/api/logs/pl-api"
                "?log_filter=resource.type=%22bigquery_resource%22"
                "&log_project=attacker-controlled-project"
            )
        assert r.status_code == 200
        args = mock_query.call_args.args
        # Project is manifest-derived, NOT attacker-controlled
        assert args[0] == "trusted-project"
        assert args[0] != "attacker-controlled-project"
        # Filter is manifest-derived, NOT attacker-controlled
        assert args[1] == 'resource.type="gce_instance"'
        assert "bigquery_resource" not in args[1]

    def test_unknown_node_id_returns_canonical_error_without_calling_gcp(self):
        """REQ-704: ids that don't resolve via manifest or discovery cache never reach GCP."""
        with patch("src.api.routes.logs.verify_token") as mock_verify, \
             patch("src.api.routes.logs._query_logs_with_filter") as mock_query, \
             patch("src.api.routes.logs._resolve_node") as mock_resolve:
            mock_verify.return_value = None
            mock_resolve.return_value = ("unknown", None, None)
            r = _client().get("/api/logs/attacker-injected-node")
        assert r.status_code == 200
        body = r.json()
        assert body == {
            "node_id": "attacker-injected-node",
            "entries": [],
            "count": 0,
            "error": "GlassHood does not know this part, so it cannot look up its logs.",
        }
        mock_query.assert_not_called()

    def test_manifest_node_without_declared_logs_falls_back_to_project_default(self):
        """REQ-212 (retained): existing node, no monitoring.logs → DEFAULT_FILTER on GCP_PROJECT_ID."""
        with patch("src.api.routes.logs.verify_token") as mock_verify, \
             patch("src.api.routes.logs._query_logs_with_filter") as mock_query, \
             patch("src.api.routes.logs._resolve_node") as mock_resolve:
            mock_verify.return_value = None
            mock_resolve.return_value = ("manifest_default",
                                         "configured-project",
                                         'resource.type="gce_instance"')
            mock_query.return_value = [{"timestamp": "t", "severity": "INFO", "message": "m"}]
            r = _client().get("/api/logs/pl-lb")
        assert r.status_code == 200
        args = mock_query.call_args.args
        assert args[0] == "configured-project"
        assert args[1] == 'resource.type="gce_instance"'

    def test_lines_clamped_to_lower_bound(self):
        """lines<=0 → >=1."""
        with patch("src.api.routes.logs.verify_token") as mock_verify, \
             patch("src.api.routes.logs._query_logs_with_filter") as mock_query, \
             patch("src.api.routes.logs._resolve_node") as mock_resolve:
            mock_verify.return_value = None
            mock_resolve.return_value = ("manifest_logs", "p", "f")
            mock_query.return_value = []
            _client().get("/api/logs/pl-api?lines=0")
        args = mock_query.call_args.args
        assert args[2] >= 1, f"lines should be clamped to >=1, got {args[2]}"

    def test_lines_clamped_to_upper_bound(self):
        """lines>500 → 500 (REQ-GHA-032 clause 12: several screens, not unbounded)."""
        with patch("src.api.routes.logs.verify_token") as mock_verify, \
             patch("src.api.routes.logs._query_logs_with_filter") as mock_query, \
             patch("src.api.routes.logs._resolve_node") as mock_resolve:
            mock_verify.return_value = None
            mock_resolve.return_value = ("manifest_logs", "p", "f")
            mock_query.return_value = []
            _client().get("/api/logs/pl-api?lines=10000")
        args = mock_query.call_args.args
        assert args[2] == 500, f"lines should be clamped to 500, got {args[2]}"

    def test_the_window_opens_with_several_screens(self):
        """REQ-GHA-032 clause 12: 300 lines by default."""
        with patch("src.api.routes.logs.verify_token") as mock_verify, \
             patch("src.api.routes.logs._query_logs_with_filter") as mock_query, \
             patch("src.api.routes.logs._resolve_node") as mock_resolve:
            mock_verify.return_value = None
            mock_resolve.return_value = ("manifest_logs", "p", "f")
            mock_query.return_value = []
            _client().get("/api/logs/pl-api")
        assert mock_query.call_args.args[2] == 300

    def test_earlier_lines_come_from_before_the_oldest_shown_within_the_week(self):
        """REQ-GHA-032 clause 13: `before` narrows the 7-day window to what is older than the oldest line shown."""
        from datetime import datetime, timezone
        from urllib.parse import quote
        from src.api.routes.logs import QUIET_FALLBACK, EARLIER_EMPTY_NOTE
        line = {"timestamp": "2026-11-09 09:00:00.000000+00:00", "severity": "INFO", "message": "m"}
        # the oldest line's own text, in the GCP and the Azure form, sent as the window sends it (encoded)
        for shown, answer in [("2026-11-09 10:00:00.123456+00:00", [line]), ("2026-11-09T10:00:00.1234567Z", [])]:
            with patch("src.api.routes.logs.verify_token", return_value=None), \
                 patch("src.api.routes.logs._query_logs_with_filter", return_value=answer) as mock_query, \
                 patch("src.api.routes.logs._resolve_node", return_value=("manifest_logs", "p", "f")):
                r = _client().get(f"/api/logs/pl-api?before={quote(shown, safe='')}")
            args = mock_query.call_args.args
            assert args[2] == 300 and args[3] == QUIET_FALLBACK
            # the boundary is included; a time finer than a microsecond rounds up so nothing is skipped
            assert args[4] == datetime(2026, 11, 9, 10, 0, 0, 123456 if answer else 123457, tzinfo=timezone.utc)
            body = r.json()
            assert body["earlier"] is True and body["window"] == "7d" and body["entries"] == answer
            assert body.get("note") == (None if answer else EARLIER_EMPTY_NOTE)

    def test_an_unreadable_before_is_refused(self):
        with patch("src.api.routes.logs.verify_token", return_value=None), \
             patch("src.api.routes.logs._resolve_node", return_value=("manifest_logs", "p", "f")):
            r = _client().get("/api/logs/pl-api?before=yesterday")
        assert r.status_code == 400

    def test_the_gcp_filter_narrows_to_before_the_oldest_shown(self):
        from datetime import datetime, timezone
        from src.api.routes.logs import _query_logs_with_filter, QUIET_FALLBACK
        before = datetime(2026, 11, 9, 10, 0, tzinfo=timezone.utc)
        with patch("google.cloud.logging_v2.Client") as mock_client:
            mock_client.return_value.list_entries.return_value = []
            _query_logs_with_filter("p", 'resource.type="x"', 300, QUIET_FALLBACK, before)
        sent = mock_client.return_value.list_entries.call_args.kwargs["filter_"]
        assert sent.startswith('(resource.type="x") AND timestamp>="') and 'AND timestamp<="2026-11-09T10:00:00+00:00"' in sent

    def test_a_provider_s_earlier_updates_are_the_ones_older_than_the_oldest_shown(self):
        rows = [{"timestamp": "2026-11-09T10:30:00Z", "severity": "WARNING", "message": "new"},
                {"timestamp": "2026-11-09T09:30:00Z", "severity": "WARNING", "message": "old"}]
        with patch("src.api.routes.logs.verify_token", return_value=None), \
             patch("src.collectors.statuspage.log_entries", return_value={"entries": rows, "note": None}):
            r = _client().get("/api/logs/cf-x?before=2026-11-09T10:00:00Z")
            r2 = _client().get("/api/logs/cf-x?before=2026-11-09T09:00:00Z")
        assert [e["message"] for e in r.json()["entries"]] == ["old"] and r.json()["earlier"] is True
        assert r2.json()["entries"] == [] and r2.json()["note"] == "No earlier lines in the last 7 days."

    def test_no_legacy_per_node_filter_dicts(self):
        """Truly-stale NODE_FILTERS / TYPE_FILTERS / _vm / _query_logs stay removed.
        DEFAULT_FILTER stays as the single project-scoped fallback (REQ-212)."""
        import src.api.routes.logs as mod
        for sym in ("NODE_FILTERS", "TYPE_FILTERS", "_query_logs", "_vm"):
            assert not hasattr(mod, sym), f"Legacy fallback symbol {sym} still present"
        assert hasattr(mod, "DEFAULT_FILTER"), \
            "REQ-212: DEFAULT_FILTER constant remains the project-scoped default"

    def test_import_error_path_returns_explanatory_error(self):
        """When google-cloud-logging is unavailable, surface that explicitly.

        Must remain a 200 with a payload error (graceful), never a 500.
        """
        with patch("src.api.routes.logs.verify_token") as mock_verify, \
             patch("src.api.routes.logs._query_logs_with_filter",
                   side_effect=ImportError("google-cloud-logging missing")), \
             patch("src.api.routes.logs._resolve_node") as mock_resolve:
            mock_verify.return_value = None
            mock_resolve.return_value = ("manifest_logs", "p", "f")
            r = _client().get("/api/logs/pl-api")
        assert r.status_code == 200
        body = r.json()
        assert body["entries"] == []
        assert body["count"] == 0
        assert "google-cloud-logging not installed" in body["error"]

    def test_generic_exception_path_returns_failure_error(self):
        """Other failures from Cloud Logging surface as a plain 'could not read'
        message and remain a graceful 200 OK with an error payload."""
        with patch("src.api.routes.logs.verify_token") as mock_verify, \
             patch("src.api.routes.logs._query_logs_with_filter",
                   side_effect=RuntimeError("transient gcp blip")), \
             patch("src.api.routes.logs._resolve_node") as mock_resolve:
            mock_verify.return_value = None
            mock_resolve.return_value = ("manifest_logs", "p", "f")
            r = _client().get("/api/logs/pl-api")
        assert r.status_code == 200
        body = r.json()
        assert body["error"].startswith("GlassHood could not read this part's logs:")
        assert "transient gcp blip" in body["error"]


class TestQuietPart:
    """REQ-GHA-032 clause 7: no lines in the last hour → the latest lines from the
    last 7 days, said in plain words; nothing at all → a plain reason."""

    def _get(self, results):
        with patch("src.api.routes.logs.verify_token"), \
             patch("src.api.routes.logs._query_logs_with_filter", side_effect=results) as mock_query, \
             patch("src.api.routes.logs._resolve_node", return_value=("manifest_logs", "p", "f")):
            body = _client().get("/api/logs/cv-fw-lb").json()
        return body, mock_query

    def test_busy_part_shows_the_last_hour_only(self):
        body, q = self._get([[{"timestamp": "t", "severity": "INFO", "message": "m"}]])
        assert body["window"] == "1h" and body["count"] == 1 and "note" not in body
        assert q.call_count == 1

    def test_quiet_part_shows_last_7_days_and_says_so(self):
        from datetime import timedelta
        body, q = self._get([[], [{"timestamp": "t", "severity": "NOTICE", "message": "rule changed"}]])
        assert body["window"] == "7d" and body["count"] == 1
        assert body["note"].startswith("No log lines in the last hour")
        assert q.call_args.args[3] == timedelta(days=7)
        assert q.call_args.args[:2] == ("p", "f")

    def test_silent_part_gives_a_plain_reason(self):
        body, _ = self._get([[], []])
        assert body["count"] == 0 and body["note"] == "No log lines for this part in the last 7 days."


class TestReadableLines:
    """REQ-GHA-032: load balancer requests and change records read as one plain line."""

    def _entry(self, payload=None, http_request=None):
        from types import SimpleNamespace
        return SimpleNamespace(payload=payload, http_request=http_request, timestamp="t", severity="INFO")

    def test_load_balancer_request(self):
        from src.api.routes.logs import _readable
        line = _readable(self._entry({"statusDetails": "response_sent_by_backend"},
                                     {"requestMethod": "GET", "status": 200, "requestUrl": "https://coldvault.ai/api/health",
                                      "latency": "0.012s", "remoteIp": "1.2.3.4"}))
        assert line == "GET 200 https://coldvault.ai/api/health · 0.012s · from 1.2.3.4"

    def test_change_record(self):
        from src.api.routes.logs import _readable
        line = _readable(self._entry({"methodName": "v1.compute.firewalls.patch",
                                      "authenticationInfo": {"principalEmail": "admin@example.com"},
                                      "resourceName": "projects/p/global/firewalls/coldvault-allow-lb"}))
        assert line == "v1.compute.firewalls.patch by admin@example.com on projects/p/global/firewalls/coldvault-allow-lb"

    def test_text_and_message_lines_unchanged(self):
        from src.api.routes.logs import _readable
        assert _readable(self._entry("plain text")) == "plain text"
        assert _readable(self._entry({"message": "app line"})) == "app line"
        assert _readable(self._entry(None)) == ""


class TestFilterParenthesization:
    """REQ-705: the manifest filter is wrapped in parens before the
    AND timestamp>=... clause so OR clauses inside the manifest filter
    can't push the timestamp constraint into a wider scope."""

    def _captured_filter(self, log_filter: str) -> str:
        """Call _query_logs_with_filter with a mocked Cloud Logging client
        and return the filter_ kwarg list_entries was invoked with."""
        from unittest.mock import MagicMock
        captured = {}

        class FakeEntry:
            timestamp = "t"
            severity = "INFO"
            payload = "p"

        def fake_client_factory(project=None):
            client = MagicMock()
            def list_entries(filter_=None, **_kw):
                captured["filter_"] = filter_
                return iter([FakeEntry()])
            client.list_entries = list_entries
            return client

        with patch("google.cloud.logging_v2.Client", side_effect=fake_client_factory):
            from src.api.routes.logs import _query_logs_with_filter
            _query_logs_with_filter("p", log_filter, max_entries=10)
        return captured["filter_"]

    def test_simple_filter_is_wrapped(self):
        filter_str = self._captured_filter('resource.type="gce_instance"')
        # Begins with the wrapped manifest filter
        assert filter_str.startswith('(resource.type="gce_instance") AND timestamp>='), \
            f"Manifest filter must be parenthesized; got: {filter_str}"

    def test_or_containing_filter_preserves_timestamp_scope(self):
        """REQ-705 core case: without parens the OR would let entries from any
        time bypass the timestamp constraint. With parens the timestamp clause
        binds across the whole OR group."""
        filter_str = self._captured_filter(
            'severity=ERROR OR resource.type="other"'
        )
        assert filter_str.startswith('(severity=ERROR OR resource.type="other") AND timestamp>='), \
            f"OR-containing manifest filter must remain parenthesized; got: {filter_str}"

    def test_parens_are_unconditional(self):
        """The wrap doesn't sniff content — every manifest filter is parenthesized
        for consistency."""
        for f in ['x=1', 'a AND b', 'severity=ERROR']:
            assert self._captured_filter(f).startswith(f"({f}) AND timestamp>="), \
                f"Filter {f!r} should be wrapped unconditionally"


class TestDemoRouteIsStatic:
    """REQ-704 audit verifiability: programmatically prove that the demo
    log route serves static data and never queries GCP Cloud Logging."""

    def test_demo_module_does_not_import_gcp_logging(self):
        """The demo route module must not import google.cloud.logging — that's
        the structural guarantee that it can't issue cross-project GCP queries
        the way the main route used to be able to under client-supplied
        log_project."""
        import src.api.routes.demo as demo
        import inspect

        source = inspect.getsource(demo)
        # No GCP Cloud Logging import — even lazily inside a function.
        assert "google.cloud.logging" not in source, (
            "Demo route must not import google.cloud.logging — that would "
            "reopen the REQ-704 attack surface on /api/demo/logs"
        )
        # No reference to the main query helper either.
        assert "_query_logs_with_filter" not in source

    def test_demo_logs_returns_only_static_diagnostics(self):
        """Functional verification: /api/demo/logs serves entries derived from
        the in-memory DEMO_TOPOLOGY blob, with no upstream service call."""
        from src.api.routes.demo import router as demo_router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(demo_router)
        # Patch httpx + google.cloud.logging in the demo module's namespace
        # to assert absence of any outbound call would surface as
        # AttributeError if accessed.
        with patch.dict("sys.modules", {"google.cloud.logging_v2": None}):
            r = TestClient(app).get("/api/demo/logs/pl-api")
        assert r.status_code == 200
        body = r.json()
        # Static path always produces a structured response with the same id.
        assert body["node_id"] == "pl-api"
        assert isinstance(body["entries"], list)
        assert isinstance(body["count"], int)

    def test_resolve_unknown_id_short_circuits_before_gcp_with_attacker_params(self):
        """End-to-end: unknown id + attacker query params still never reaches GCP."""
        with patch("src.api.routes.logs.verify_token") as mock_verify, \
             patch("src.api.routes.logs._query_logs_with_filter") as mock_query, \
             patch("src.api.routes.logs._resolve_node") as mock_resolve:
            mock_verify.return_value = None
            mock_resolve.return_value = ("unknown", None, None)
            r = _client().get(
                "/api/logs/whatever?log_filter=resource.type=%22bigquery_resource%22"
                "&log_project=other-project"
            )
        assert r.json()["error"].startswith("GlassHood does not know this part")
        mock_query.assert_not_called()


class TestResolveNodeUnmocked:
    """REQ-704: integration-style tests that exercise _resolve_node directly,
    NOT via a mock. These verify the lazy-import path (_load_manifests +
    compile_all) and the resolver logic itself — the parts the
    higher-level route tests mock past.

    9r-review fix: previous suite mocked _resolve_node end-to-end so the
    actual security boundary was never exercised by tests.
    """

    def test_unknown_id_returns_unknown_status_with_no_gcp_call(self):
        """Real call with an id that exists in neither the manifest nor the
        discovery cache returns ("unknown", None, None) and reaches GCP zero
        times."""
        from src.api.routes.logs import _resolve_node

        # Mock the manifest source to be empty (no nodes); leave the rest
        # of the lazy-import chain real so any import-rename regression
        # surfaces here.
        with patch("src.api.routes.manifests._load_manifests", return_value=[]):
            status, project, log_filter = _resolve_node("nonexistent-node-xyz")
        assert status == "unknown"
        assert project is None
        assert log_filter is None

    def test_manifest_node_with_declared_logs_resolves_correctly(self):
        """Real resolver returns the manifest's declared filter+project."""
        from src.api.routes.logs import _resolve_node

        fake_manifest = [{
            "nodes": [{
                "id": "pl-api",
                "monitoring": {
                    "logs": [{
                        "filter": 'jsonPayload.container.name="/platform"',
                        "project": "trusted-project",
                    }]
                }
            }]
        }]
        with patch("src.api.routes.manifests._load_manifests", return_value=fake_manifest), \
             patch("src.manifest_compiler.compile_all", return_value=fake_manifest):
            status, project, log_filter = _resolve_node("pl-api")
        assert status == "manifest_logs"
        assert project == "trusted-project"
        assert log_filter == 'jsonPayload.container.name="/platform"'

    def test_manifest_node_without_logs_falls_back_to_default(self):
        """Real resolver returns DEFAULT_FILTER + GCP_PROJECT_ID when the node
        exists but has no monitoring.logs."""
        from src.api.routes.logs import _resolve_node, DEFAULT_FILTER

        fake_manifest = [{
            "nodes": [{"id": "pl-lb", "monitoring": {}}]
        }]
        with patch("src.api.routes.manifests._load_manifests", return_value=fake_manifest), \
             patch("src.manifest_compiler.compile_all", return_value=fake_manifest), \
             patch("src.api.routes.logs.GCP_PROJECT_ID", "configured-project"):
            status, project, log_filter = _resolve_node("pl-lb")
        assert status == "manifest_default"
        assert log_filter == DEFAULT_FILTER

    def test_compiled_child_node_resolves(self):
        """Static children (compiled, not template-resolved) are reachable via
        the recursive _walk_node walk."""
        from src.api.routes.logs import _resolve_node

        fake_manifest = [{
            "nodes": [{
                "id": "pl-parent",
                "children": [
                    {
                        "id": "pl-parent-child",
                        "monitoring": {
                            "logs": [{
                                "filter": 'resource.type="cloud_run_revision"',
                                "project": "trusted-project",
                            }]
                        }
                    }
                ]
            }]
        }]
        with patch("src.api.routes.manifests._load_manifests", return_value=fake_manifest), \
             patch("src.manifest_compiler.compile_all", return_value=fake_manifest):
            status, project, log_filter = _resolve_node("pl-parent-child")
        assert status == "manifest_logs"
        assert log_filter == 'resource.type="cloud_run_revision"'

    def test_route_end_to_end_with_unknown_id_unmocked_resolver(self):
        """End-to-end through the FastAPI route WITHOUT mocking _resolve_node:
        an attacker-constructed unknown id never reaches Cloud Logging."""
        with patch("src.api.routes.logs.verify_token") as mock_verify, \
             patch("src.api.routes.logs._query_logs_with_filter") as mock_query, \
             patch("src.api.routes.manifests._load_manifests", return_value=[]):
            mock_verify.return_value = None
            r = _client().get(
                "/api/logs/attacker-injected-node"
                "?log_filter=resource.type=%22bigquery_resource%22"
                "&log_project=other-project"
            )
        body = r.json()
        assert body["error"].startswith("GlassHood does not know this part")
        mock_query.assert_not_called()


class TestDiscoveredVmChildren:
    """REQ-GHA-032: the boxes inside a discovered VM (container, app, embeddings)
    resolve from that VM's cache entry and its template, never from the browser."""

    TEMPLATE = [{
        "id_suffix": "-docker",
        "monitoring": {"logs": [{"project": "p", "filter": 'instance="{vm_name}" AND container="/app"'}]},
        "children": [
            {"id_suffix": "-api",
             "monitoring": {"logs": [{"project": "p", "filter": 'instance="{vm_name}" AND severity'}]}},
            {"id_suffix": "-embeddings", "status": "not checked"},
        ],
    }]

    def _resolve(self, node_id):
        from src.api.routes.logs import _resolve_node
        cache = {"vm-cv-mig-ab12": {"_parent": "cv-mig", "instance_id": "123"}}
        with patch("src.api.routes.manifests._load_manifests", return_value=[]), \
             patch("src.manifest_compiler.compile_all", return_value=[]), \
             patch("src.collectors.manifest_metrics.get_node_status", side_effect=cache.get), \
             patch("src.collectors.manifest_metrics.get_all_statuses", return_value=cache), \
             patch("src.collectors.manifest_metrics.get_children_template", return_value=self.TEMPLATE):
            return _resolve_node(node_id)

    def test_container_box(self):
        assert self._resolve("vm-cv-mig-ab12-docker") == ("discovered_vm", "p", 'instance="cv-mig-ab12" AND container="/app"')

    def test_app_box(self):
        assert self._resolve("vm-cv-mig-ab12-api") == ("discovered_vm", "p", 'instance="cv-mig-ab12" AND severity')

    def test_embeddings_box_shows_the_container_it_runs_in(self):
        assert self._resolve("vm-cv-mig-ab12-embeddings") == ("discovered_vm", "p", 'instance="cv-mig-ab12" AND container="/app"')

    def test_child_of_an_unknown_vm_stays_unknown(self):
        assert self._resolve("vm-other-vm-docker") == ("unknown", None, None)
        assert self._resolve("vm-cv-mig-ab12-nothing") == ("unknown", None, None)
