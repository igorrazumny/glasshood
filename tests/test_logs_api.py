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
            "error": "Unknown node",
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
        """lines>200 → 200."""
        with patch("src.api.routes.logs.verify_token") as mock_verify, \
             patch("src.api.routes.logs._query_logs_with_filter") as mock_query, \
             patch("src.api.routes.logs._resolve_node") as mock_resolve:
            mock_verify.return_value = None
            mock_resolve.return_value = ("manifest_logs", "p", "f")
            mock_query.return_value = []
            _client().get("/api/logs/pl-api?lines=10000")
        args = mock_query.call_args.args
        assert args[2] == 200, f"lines should be clamped to 200, got {args[2]}"

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
        """Other failures from Cloud Logging surface as a 'Log collection failed'
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
        assert body["error"].startswith("Log collection failed:")
        assert "transient gcp blip" in body["error"]


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
        assert r.json()["error"] == "Unknown node"
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
        assert body["error"] == "Unknown node"
        mock_query.assert_not_called()
