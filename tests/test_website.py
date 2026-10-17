"""REQ-GHA-018 clauses 1-3: structural guards for the public site (website/).

Static, dependency-free assertions on the files the site serves, mirroring the
TestRobin site's guard suite: the four surfaces, Open app to app.glasshood.ai, the
app's state read from the wake controller and never from the app, a form-only contact
on the shared mail function, no email address anywhere, per-page metadata, the older
demo addresses forwarded, and the architecture page served from one set of files at
both addresses. website/build.sh is run here into a temporary folder.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_W = ROOT / "website"
_PUB = _W / "public"
_ARCH = ROOT / "architecture"
_read = lambda p: Path(p).read_text(encoding="utf-8")

_PAGES = {"/": _PUB / "index.html", "/contact/": _PUB / "contact/index.html"}
_NAV_PAGES = (_PUB / "index.html", _PUB / "contact/index.html", _PUB / "404.html")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")


def _nav(html):
    return html.split('<nav class="nav"', 1)[1].split("</nav>", 1)[0]


@pytest.mark.parametrize("page", _NAV_PAGES, ids=lambda p: p.name if p.name != "index.html" else p.parent.name)
def test_every_page_has_the_four_surfaces(page):
    nav = _nav(_read(page))
    for href in ('href="/"', 'href="/architecture/"', 'href="/contact/"', 'href="https://app.glasshood.ai"'):
        assert href in nav, f"{page.name}: nav misses {href}"
    assert ">Open app<" in nav
    for word in ("register", "sign up", "signup"):
        assert word not in nav.lower(), "no registration surface (clause 1)"


@pytest.mark.parametrize("path,page", _PAGES.items())
def test_the_current_page_is_marked_in_the_nav(path, page):
    assert f'href="{path}" aria-current="page"' in _nav(_read(page))


def test_no_email_address_in_anything_served():
    served = [p for p in list(_PUB.rglob("*")) + list(_ARCH.rglob("*")) + list((_W / "architecture").rglob("*"))
              if p.is_file() and p.suffix in {".html", ".css", ".js", ".json", ".txt", ".xml", ".svg"}]
    assert served
    found = [str(p.relative_to(ROOT)) for p in served if _EMAIL.search(_read(p)) or "mailto:" in _read(p).lower()]
    assert not found, f"no email address may appear on the site (clause 3): {found}"


def test_contact_is_a_form_on_the_shared_mail_function_tagged_glasshood():
    js = _read(_PUB / "assets/contact.js")
    assert "https://sendcontactform-llkttegjbq-oa.a.run.app" in js, "the 9robots.ai form's mail function"
    assert "source: glasshood.ai" in js and "[glasshood.ai] Contact form" in js and "category: 'GlassHood'" in js
    assert "grecaptcha.ready(" in js and "grecaptcha.execute(" in js, "reCAPTCHA with the ready() guard"
    html = _read(_PUB / "contact/index.html")
    assert 'id="contact-form"' in html and "/assets/contact.js" in html
    for field in ("contact-name", "contact-email", "contact-message"):
        assert f'id="{field}"' in html and "required" in html.split(f'id="{field}"', 1)[1].split(">", 1)[0]
    assert "policies.google.com/privacy" in html and "policies.google.com/terms" in html, \
        "Google's attribution (the badge is hidden)"


@pytest.mark.parametrize("path,page", _PAGES.items())
def test_each_page_has_its_own_title_description_canonical_and_open_graph(path, page):
    html = _read(page)
    url = "https://glasshood.ai" + path
    assert f'<link rel="canonical" href="{url}">' in html
    assert f'<meta property="og:url" content="{url}">' in html
    title = re.search(r"<title>([^<]+)</title>", html).group(1)
    assert f'<meta property="og:title" content="{title}">' in html
    assert re.search(r'<meta name="description" content="[^"]+">', html)
    assert '<link rel="icon" href="/assets/icon-32.png">' in html
    assert "noindex" not in html


def test_titles_differ_between_pages():
    titles = {re.search(r"<title>([^<]+)</title>", _read(p)).group(1) for p in _PAGES.values()}
    assert len(titles) == len(_PAGES)


def test_not_found_page_is_noindex_without_a_canonical():
    html = _read(_PUB / "404.html")
    assert '<meta name="robots" content="noindex">' in html and "canonical" not in html
    assert "noindex" in _read(_W / "architecture/404.html")


def test_sitemap_lists_the_indexable_pages_and_robots_names_it():
    sm = _read(_PUB / "sitemap.xml")
    for path in _PAGES:
        assert f"<loc>https://glasshood.ai{path}</loc>" in sm
    # The architecture page is noindex today, so it stays out of the sitemap until it is not.
    if "noindex" in _read(_ARCH / "index.html"):
        assert "/architecture/" not in sm
    assert "Sitemap: https://glasshood.ai/sitemap.xml" in _read(_PUB / "robots.txt")


def test_older_demo_addresses_go_to_the_demo_in_the_app():
    cfg = json.loads(_read(_PUB / "staticwebapp.config.json"))
    routes = {r["route"]: r for r in cfg["routes"]}
    for route in ("/demo*", "/view*"):
        assert routes[route]["redirect"] == "https://app.glasshood.ai/demo", route
        assert routes[route]["statusCode"] in (301, 302)
    home = _read(_PUB / "index.html")
    assert "q.has('demo') || q.has('view')" in home and "location.replace('https://app.glasshood.ai/demo')" in home
    assert home.index("location.replace") < home.index("</head>"), "forward before the page renders"


def test_both_hosts_revalidate_everything_and_send_security_headers():
    for cfg_path in (_PUB / "staticwebapp.config.json", _W / "architecture/staticwebapp.config.json"):
        cfg = json.loads(_read(cfg_path))
        headers = cfg["globalHeaders"]
        assert headers["Cache-Control"] == "no-cache, must-revalidate", cfg_path
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert "Referrer-Policy" in headers and "X-Frame-Options" in headers
        assert cfg["responseOverrides"]["404"]["rewrite"] == "/404.html"
        assert "immutable" not in json.dumps(cfg)


# --- the app's state (clause 1) ---

_STATE = _ARCH / "app-state.js"
_STATES = ("asleep", "waking", "awake", "going-to-sleep")


def test_the_state_is_read_from_the_controller_only_and_never_wakes_the_app():
    src = _read(_STATE)
    assert "CONTROLLER + '/status'" in src
    assert "app.glasshood.ai" not in src, "loading a public page never contacts the app"
    assert "POST" not in src and "method" not in src, "the public pages only read the state"
    assert "credentials" not in src, "no cookies sent to the controller"
    assert "typeof state === 'string'" in src, "only a string state is accepted"
    assert "if (!CONTROLLER" in src, "nothing is requested while the controller's address is unset"
    labels = dict(re.findall(r"""['"]?([a-z-]+)['"]?:\s*'([^']+)'""", src.split("LABELS", 1)[1].split("}", 1)[0]))
    assert set(labels) == set(_STATES), labels


@pytest.mark.parametrize("page", _NAV_PAGES + (_ARCH / "index.html",), ids=lambda p: str(p.relative_to(ROOT)))
def test_every_public_page_shows_the_state(page):
    html = _read(page)
    assert re.search(r'<span class="app-state" data-app-state role="status" hidden>', html)
    assert "/architecture/app-state.js" in html


def test_the_state_sits_with_open_app_and_with_launch_live_demo():
    for page in _NAV_PAGES:
        app = _read(page).split('<div class="nav-app">', 1)[1].split("</div>", 1)[0]
        assert app.index("data-app-state") < app.index('href="https://app.glasshood.ai"')
    assert re.search(r"Launch live demo</a><span class=\"app-state\" data-app-state", _read(_ARCH / "index.html"))


# --- one set of architecture files at both addresses (clause 2) ---


def test_build_serves_the_architecture_page_from_one_set_of_files(tmp_path):
    out = tmp_path / "out"
    r = subprocess.run(["bash", str(_W / "build.sh"), str(out)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    for f in _ARCH.rglob("*"):
        if f.is_file() and f.name != ".DS_Store":
            rel = f.relative_to(_ARCH)
            assert (out / "site/architecture" / rel).read_bytes() == f.read_bytes(), rel
            assert (out / "architecture/architecture" / rel).read_bytes() == f.read_bytes(), rel
    # architecture.glasshood.ai answers the page itself at / (a direct 200, not a redirect)
    assert (out / "architecture/index.html").read_bytes() == (_ARCH / "index.html").read_bytes()
    assert "redirect" not in _read(out / "architecture/staticwebapp.config.json")
    assert (out / "site/index.html").read_bytes() == (_PUB / "index.html").read_bytes()


def test_build_refuses_an_email_address(tmp_path):
    src = tmp_path / "repo"
    for d in ("website", "architecture"):
        shutil.copytree(ROOT / d, src / d, ignore=shutil.ignore_patterns("out", ".DS_Store"))
    (src / "website/public/contact/index.html").write_text("<p>write to someone@example.com</p>", encoding="utf-8")
    r = subprocess.run(["bash", str(src / "website/build.sh"), str(tmp_path / "out")], capture_output=True, text=True)
    assert r.returncode == 1 and "email address" in r.stderr and "contact/index.html" in r.stderr, r.stderr
