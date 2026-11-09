"""REQ-GHA-049: agents' credentials, change feed, responsibility and corrections."""
from unittest.mock import patch

import pytest
import yaml
from fastapi.testclient import TestClient

from src.analysis import agent_access as store
from src.analysis import vertex_overview as ov
from src.api.server import app

LAND = {"product": "cv", "solution": "ColdVault", "responsible_agent": "architect", "api_token": "s3cret",
        "environments": [{"environment": "prod", "findings": [{"id": "f", "text": "note"}],
                          "nodes": [{"id": "a", "label": "App", "monitoring": {"probe": {"type": "http", "password": "x"}}},
                                    {"id": "gone", "label": "Old"}]}]}
NODES = [{"id": "a", "label": "App", "project": "cv", "status": "healthy", "metrics": {"_check_description": "Answers", "_last_poll": 5}},
         {"id": "gone", "label": "Old", "project": "cv", "status": "not checked", "metrics": {}}]


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_STATE_DIR", str(tmp_path))
    store._state.clear(); store._loaded[0] = False; store._started[0] = None
    d = tmp_path / "m"; d.mkdir(); (d / "cv.yaml").write_text(yaml.safe_dump(LAND))
    import src.api.routes.manifests as m
    monkeypatch.setattr(m, "MANIFEST_DIR", d)
    import src.api.routes.topology as t
    monkeypatch.setattr(t, "get_topology_data", lambda: {"nodes": NODES})
    monkeypatch.setattr(ov, "system_cards", lambda: {"cv": {"condition": "attention", "score": 6, "summary": "s", "analyzed_at": 1}})
    monkeypatch.setattr(ov, "_outside_products", lambda: set())
    import src.rules.engine as e
    monkeypatch.setattr(e, "get_alerts", lambda: [{"number": 7, "severity": "warning", "title": "T", "node_id": "a"},
                                                  {"number": 8, "kind": "example", "severity": "warning", "title": "E", "node_id": "a"}])


def client(agent=None):
    h = {"X-Agent-Key": store.create_key(agent)} if agent else {}
    return TestClient(app, headers=h)


def test_a_credential_is_required_survives_a_restart_and_can_be_withdrawn():
    assert client().get("/api/agents/systems").status_code == 401
    key = store.create_key("tank")
    assert key not in str(store._state["keys"])
    store._state.clear(); store._loaded[0] = False
    c = TestClient(app, headers={"X-Agent-Key": key})
    assert c.get("/api/agents/systems").status_code == 200
    store.withdraw_key("tank")
    assert c.get("/api/agents/systems").status_code == 401


def test_list_and_one_system_use_the_cards_words():
    c = client("tank")
    s = c.get("/api/agents/systems").json()["systems"][0]
    assert (s["name"], s["group"], s["status"]) == ("ColdVault", "Proprietary systems", "Needs attention")
    one = c.get("/api/agents/systems/cv").json()
    assert one["score"] == 6 and [a["number"] for a in one["open_alerts"]] == [7] and len(one["components"]) == 2
    assert c.get("/api/agents/systems/nope").status_code == 404


def test_each_change_once_and_a_restart_changes_nothing():
    s = lambda w, al: store.record_changes({"cv": {"condition": w}}, {"cv": al}, now=T[0])
    T = [0]
    s("normal", [{"number": 1, "title": "x", "severity": "warning"}])     # the grace after a restart
    assert store._state.get("events", []) == []
    T[0] = 700; s("normal", [{"number": 1, "title": "x", "severity": "warning"}])
    T[0] = 800; s("failing", [{"number": 2, "title": "y", "severity": "critical"}])
    assert [e["kind"] for e in store.changes_for("a")] == ["status_changed", "alert_new", "alert_ended"]
    assert store.changes_for("a") == [] and len(store.changes_for("b", "cv")) == 3
    store._state.clear(); store._loaded[0] = False; store._started[0] = None
    T[0] = 900; s("failing", [])          # just restarted: alarms not rebuilt yet
    assert store.changes_for("a") == []


def test_a_system_without_a_record_produces_no_change():
    store._started[0] = -1000
    store.record_changes({"cv": {}}, {"cv": []}, now=1)
    assert store._state["snapshot"] == {}


def test_full_setup_is_for_the_responsible_agent_and_shows_no_credential():
    assert client("tank").get("/api/agents/systems/cv/setup").status_code == 403
    assert client("tank").get("/api/agents/systems/cv/verify").status_code == 403
    r = client("architect").get("/api/agents/systems/cv/setup")
    assert r.status_code == 200 and "s3cret" not in r.text and r.json()["landscape"]["version"]
    assert r.json()["setup"]["environments"][0]["findings"][0]["id"] == "f"


def test_verification_says_what_could_not_be_confirmed():
    v = client("architect").get("/api/agents/systems/cv/verify").json()
    assert v["not_confirmed"] == ["gone"]
    a = next(p for p in v["components"] if p["component"] == "a")
    assert a["confirmed"] is True and a["check_description"] == "Answers" and a["expected_check"]["password"] != "x"


def test_a_correction_is_recorded_for_the_operator_and_changes_nothing():
    body = {"kind": "no_longer_exists", "component": "gone", "description": "Removed", "evidence": "10:42Z"}
    assert client("tank").post("/api/agents/systems/cv/corrections", json=body).status_code == 403
    c = client("architect")
    assert c.post("/api/agents/systems/cv/corrections", json={**body, "kind": "x"}).status_code == 400
    assert c.post("/api/agents/systems/cv/corrections", json=body).status_code == 200
    assert store.corrections()[0]["agent"] == "architect"
    assert c.get("/api/agents/corrections").status_code == 403       # an agent is a viewer
    assert c.get("/api/agents/systems/cv").json()["open_alerts"]     # nothing closed


@pytest.mark.parametrize("call", [("post", "/api/agents/keys"), ("delete", "/api/agents/keys/tank"), ("post", "/api/alerts/ack")])
def test_an_agent_cannot_use_any_other_write(call):
    r = getattr(client("tank"), call[0])(call[1], **({"json": {"agent": "x"}} if call[0] == "post" else {}))
    assert r.status_code == 403


def test_unreadable_state_is_said():
    store._loaded[0] = False
    (__import__("pathlib").Path(store._file())).write_text("{bad")
    r = TestClient(app, headers={"X-Agent-Key": "k"}).get("/api/agents/systems")
    assert r.status_code == 503 and "could not be read" in r.text
