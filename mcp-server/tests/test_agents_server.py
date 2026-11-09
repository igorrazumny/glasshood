"""REQ-GHA-049: the agents' MCP server sends the agent's credential and says when GlassHood did not answer."""
import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import agents_server as a  # noqa: E402


class Answer(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *x): return False


def test_tools_send_the_credential_to_the_right_path(monkeypatch):
    seen = {}
    def opener(req, timeout):
        seen.update(url=req.full_url, key=req.get_header("X-agent-key"), method=req.method, data=req.data)
        return Answer(b'{"ok": true}')
    monkeypatch.setenv("GLASSHOOD_AGENT_KEY", "k"); monkeypatch.setenv("GLASSHOOD_URL", "http://x")
    monkeypatch.setattr(a.urllib.request, "urlopen", opener)
    assert a.get_changes("cold vault") == {"ok": True}
    assert seen["url"] == "http://x/api/agents/changes?system=cold%20vault" and seen["key"] == "k"
    a.submit_correction("cv", "missing", "c", "d", "e")
    assert seen["method"] == "POST" and json.loads(seen["data"])["evidence"] == "e"


def test_no_answer_is_said_never_guessed(monkeypatch):
    def down(req, timeout): raise urllib.error.URLError("refused")
    monkeypatch.setenv("GLASSHOOD_AGENT_KEY", "k"); monkeypatch.setattr(a.urllib.request, "urlopen", down)
    with pytest.raises(a.ToolError, match="state is unknown"):
        a.list_systems()
    monkeypatch.delenv("GLASSHOOD_AGENT_KEY")
    with pytest.raises(a.ToolError, match="not set"):
        a.list_systems()
