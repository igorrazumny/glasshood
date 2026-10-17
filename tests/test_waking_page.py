"""REQ-GHA-018 clause 6: structural guards for the waking page (deploy/waking-page/).

Static assertions on the one self-contained file that app.glasshood.ai shows while the
app wakes: it requests nothing but the wake controller, reads and starts the wake through
the agreed contract, goes only to a path on its own site when the app is awake, and gives
up with a way to ask for help after 3 minutes. The browser behaviour is checked against
mock-controller.py, next to the page.
"""
import re
from pathlib import Path

_DIR = Path(__file__).resolve().parents[1] / "deploy" / "waking-page"
_HTML = (_DIR / "index.html").read_text(encoding="utf-8")
_SCRIPT = _HTML.split("<script>", 1)[1].split("</script>", 1)[0]


def test_self_contained_and_not_indexed():
    assert '<meta name="robots" content="noindex, nofollow">' in _HTML
    # Every address the page names is the public site's, or inline data.
    for url in re.findall(r'(?:href|src)="([^"]+)"', _HTML):
        assert url.startswith(("https://glasshood.ai/", "data:")), url
    assert "url(http" not in _HTML and "@import" not in _HTML
    assert len(_HTML.encode()) < 150_000


def test_reads_and_starts_the_wake_through_the_controller_only():
    assert 'var CONTROLLER = "";' in _SCRIPT, "one constant, set when the controller exists"
    assert 'CONTROLLER + "/status"' in _SCRIPT and 'CONTROLLER + "/wake"' in _SCRIPT
    assert 'method: "POST"' in _SCRIPT
    assert "credentials" not in _SCRIPT, "no cookies sent to the controller"
    # A first visit starts the app unless it is already waking or awake.
    assert 'state === "asleep" || (first && state !== "waking" && state !== "awake")' in _SCRIPT


def test_gives_up_after_three_minutes_with_a_way_to_ask_for_help():
    assert "window.__WAKE_FAIL_AFTER_MS || 180000" in _SCRIPT
    failed = _HTML.split('<section id="failed" hidden>', 1)[1].split("</section>", 1)[0]
    assert 'href="https://glasshood.ai/contact/"' in failed and 'id="retry"' in failed


def test_the_deadline_does_not_wait_for_the_network():
    # Its own timer, not the next poll: a request that never finishes cannot hold it off.
    assert "setTimeout(fail, Math.max(0, deadline - now()))" in _SCRIPT
    assert "if (expired()) { fail(); return; }" in _SCRIPT.split("ticker = setInterval", 1)[1]
    # Every request is bounded, headers and body, and cancelled when the page gives up.
    assert "var REQUEST_MS = 10000;" in _SCRIPT and "new AbortController()" in _SCRIPT
    assert "ctrl.abort()" in _SCRIPT and "c.abort()" in _SCRIPT.split("function fail()", 1)[1]
    # A late answer is not acted on, and nobody is taken in after the deadline.
    answer = _SCRIPT.split("if (req) req.done();", 1)[1]
    assert answer.index("if (expired())") < answer.index("render(state, info)")
    assert "if (failed || expired()) { fail(); return; }" in _SCRIPT.split("function enter()", 1)[1]


def test_a_stored_attempt_is_used_only_if_it_makes_sense():
    assert "function valid(a)" in _SCRIPT and "isFinite(v)" in _SCRIPT
    load = _SCRIPT.split("function load()", 1)[1].split("function save", 1)[0]
    assert "valid(a)" in load


def test_goes_only_to_a_path_on_its_own_site():
    assert 'get("next")' in _SCRIPT
    assert "u.origin !== location.origin" in _SCRIPT and "u.pathname === location.pathname" in _SCRIPT
    assert 'next.charAt(1) === "/"' in _SCRIPT and 'next.charAt(1) === "\\\\"' in _SCRIPT
    assert "location.replace(NEXT)" in _SCRIPT


def test_every_visible_string_is_in_the_wording_block():
    text = _SCRIPT.split("var TEXT = {", 1)[1].split("};", 1)[0]
    keys = set(re.findall(r"^\s*(\w+):", text, re.M))
    used = set(re.findall(r'data-text="(\w+)"', _HTML)) | set(re.findall(r"TEXT\.(\w+)", _SCRIPT))
    assert used <= keys, used - keys
    assert "GlassHood" in text and "TestRobin" not in _HTML
