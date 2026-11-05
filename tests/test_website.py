"""REQ-GHA-018 clauses 1-3: structural guards for the public site (website/).

Static, dependency-free assertions on the files the site serves, mirroring the
TestRobin site's guard suite: the four surfaces, Log in to app.glasshood.ai, the
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
    assert ">Log in<" in nav
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


# --- the app's state (clause 1, amended 2026-11-05): the public pages do not show it ---


@pytest.mark.parametrize("page", _NAV_PAGES + (_ARCH / "index.html",), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_public_page_shows_the_app_state(page):
    html = _read(page)
    assert "app-state" not in html and "data-app-state" not in html


def test_loading_the_public_pages_contacts_neither_the_app_nor_its_wake_controller():
    assert not (_ARCH / "app-state.js").exists()
    served = [p for p in list(_PUB.rglob("*")) + list(_ARCH.rglob("*")) + list((_W / "architecture").rglob("*"))
              if p.is_file() and p.suffix in {".html", ".css", ".js", ".json"}]
    for p in served:
        assert "func-glasshood-wake" not in _read(p), p
    for script in [p for p in served if p.suffix == ".js"]:
        assert "app.glasshood.ai" not in _read(script), script


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


def _repo_copy(tmp_path):
    """A disposable copy of what build.sh reads, plus one more repository folder."""
    src = tmp_path / "repo"
    for d in ("website", "architecture"):
        shutil.copytree(ROOT / d, src / d, ignore=shutil.ignore_patterns("out", ".DS_Store"))
    (src / "docs").mkdir()
    (src / "docs/keep.md").write_text("keep", encoding="utf-8")
    return src


def _build(src, *target):
    return subprocess.run(["bash", str(src / "website/build.sh"), *map(str, target)], capture_output=True, text=True)


def _files(path):
    return {str(p.relative_to(path)): p.read_bytes() for p in sorted(path.rglob("*")) if p.is_file()}


def test_build_refuses_an_email_address(tmp_path):
    src = _repo_copy(tmp_path)
    (src / "website/public/contact/index.html").write_text("<p>write to someone@example.com</p>", encoding="utf-8")
    r = _build(src, tmp_path / "out")
    assert r.returncode == 1 and "email address" in r.stderr and "contact/index.html" in r.stderr, r.stderr


# The output folder is replaced on every build, so a target that is, or is inside, what the
# build reads must be refused before anything is deleted, whatever the path looks like.
_REFUSED = {
    "the repository": lambda s: s,
    "the repository with a slash": lambda s: f"{s}/",
    "the repository by ..": lambda s: f"{s}/website/..",
    "the folder above the repository": lambda s: s.parent,
    "the website sources": lambda s: s / "website",
    "the website sources with a slash": lambda s: f"{s}/website/",
    "the public sources": lambda s: s / "website/public",
    "a new folder inside the sources": lambda s: s / "website/public/new",
    "the architecture sources": lambda s: s / "architecture",
    "another repository folder": lambda s: s / "docs",
}


@pytest.mark.parametrize("name", _REFUSED)
def test_build_refuses_its_own_sources_and_leaves_them_intact(tmp_path, name):
    src = _repo_copy(tmp_path)
    before = _files(tmp_path)
    r = _build(src, _REFUSED[name](src))
    assert r.returncode == 1 and "refusing to build" in r.stderr, r.stderr
    assert _files(tmp_path) == before, "a refused build must not change any file"


def test_build_refuses_an_alias_of_the_repository(tmp_path):
    src = _repo_copy(tmp_path)
    alias = tmp_path / "alias"
    alias.symlink_to(src, target_is_directory=True)
    before = _files(src)
    for target in (alias, f"{alias}/", alias / "website", alias / "architecture"):
        r = _build(src, target)
        assert r.returncode == 1 and "refusing to build" in r.stderr, (target, r.stderr)
    assert _files(src) == before and alias.is_symlink()


def test_build_refuses_what_it_did_not_make(tmp_path):
    src = _repo_copy(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    (other / "keep.txt").write_text("keep", encoding="utf-8")
    plain = tmp_path / "file.txt"
    plain.write_text("keep", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(plain)
    for target in (other, plain, link):
        r = _build(src, target)
        assert r.returncode == 1 and "refusing to build" in r.stderr, (target, r.stderr)
    assert (other / "keep.txt").read_text() == "keep" and plain.read_text() == "keep" and link.is_symlink()


def test_build_replaces_only_its_own_output(tmp_path):
    src = _repo_copy(tmp_path)
    out = tmp_path / "out"
    assert _build(src, out).returncode == 0 and (out / ".glasshood-site-build").is_file()
    (out / "site/stale.txt").write_text("old", encoding="utf-8")
    assert _build(src, out).returncode == 0 and not (out / "site/stale.txt").exists()
    empty = tmp_path / "empty"
    empty.mkdir()
    assert _build(src, empty).returncode == 0 and (empty / "site/index.html").is_file()
    # the default, website/out
    assert _build(src).returncode == 0 and (src / "website/out/architecture/index.html").is_file()


# --- the look (REQ-GHA-018 clause 14): as neat and tidy as 9robots.ai, in GlassHood's colours ---


def _shared_block(css):
    start = css.index("==== masthead and footer: start ====")
    body = css[css.index("*/", start) + 2:css.index("/* ==== masthead and footer: end ====")]
    return " ".join(re.sub(r"/\*.*?\*/", "", body, flags=re.S).split())


def test_the_architecture_page_has_the_same_masthead_and_footer_styles():
    site = _shared_block(_read(_PUB / "assets/site.css"))
    assert ".nav-links a[aria-current=\"page\"]" in site and ".site-footer-row" in site and ".page-title" in site
    assert _shared_block(_read(_ARCH / "styles.css")) == site


@pytest.mark.parametrize("page", _NAV_PAGES + (_ARCH / "index.html",), ids=lambda p: str(p.relative_to(ROOT)))
def test_every_page_ends_with_the_footer(page):
    html = _read(page)
    footer = html.split('<footer class="footer">', 1)[1].split("</footer>", 1)[0]
    for label in (">Home<", ">Architecture<", ">Contact<", ">Log in<"):
        assert label in footer, label
    assert html.index("</main>" if "</main>" in html else '<div class="container">') < html.index('<footer class="footer">')
    for legal in ("©", "&copy;", "copyright", "rights reserved", "gmbh"):
        assert legal not in footer.lower(), legal


def test_the_architecture_page_carries_the_site_masthead_on_both_hosts():
    html = _read(_ARCH / "index.html")
    nav = _nav(html)
    # Absolute addresses: the same file is the page at glasshood.ai/architecture/ and at architecture.glasshood.ai.
    for href in ('href="https://glasshood.ai/"', 'href="https://glasshood.ai/contact/"', 'href="https://app.glasshood.ai"'):
        assert href in nav, href
    assert 'href="https://glasshood.ai/architecture/" aria-current="page"' in nav
    assert '<h1 class="page-title">Architecture reference</h1>' in html
    assert "pd-logo-link" not in html, "no second logo; no logo opens the app"


def test_home_has_the_two_colour_hero_and_cards_with_icons():
    home = _read(_PUB / "index.html")
    assert '<span class="hero-title-first">' in home and '<span class="hero-title-rest">' in home
    # No colour wash behind the hero (Igor, 2026-11-05: "fade out, we will remove for GlassHood").
    assert "hero-wash" not in home and "hero-wash" not in _read(_PUB / "assets/site.css")
    assert home.count('<span class="feature-icon">') == 3


def test_contact_has_labels_and_marks_the_required_fields():
    html = _read(_PUB / "contact/index.html")
    for field in ("contact-name", "contact-email", "contact-message"):
        assert f'<label for="{field}" class="form-label form-label-required">' in html, field
    assert "Required fields" in html and '<div class="form-row">' in html
    css = _read(_PUB / "assets/site.css")
    assert '.form-label-required::after{content:" *"' in css


# The masthead logo is as tall as 9robots.ai's, and so is its word (REQ-GHA-018 clause 14, amended
# 2026-11-05). 9robots.ai sizes its logo 43 px, and 39 px below 768 px (Tailwind's max-[768px] in
# 9robots-site next/components/Nav.tsx). In its image, /img/9robots-logo.png (4535 x 982), the visible
# pixels run from row 29 to 971 (the mark fills 943/982 of the height) and the word "9robots" from row
# 147 to 806 (660/982). GlassHood's masthead logo uses the same sizes and an image cut to the same shares.
_NAV_LOGO = ROOT / "architecture/img/glasshood-logo-nav.png"
_NAV_IMG = '<img src="/architecture/img/glasshood-logo-nav.png" alt="GlassHood" width="754" height="132">'
_NINEROBOTS_MARK, _NINEROBOTS_WORD = 943 / 982, 660 / 982


def _png_rgba_rows(path):
    """Width, height, bytes per pixel and decoded rows of an 8-bit, non-interlaced RGB(A) PNG."""
    import struct
    import zlib
    data, pos, idat = path.read_bytes(), 8, b""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, height, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", chunk)
            assert depth == 8 and ctype in (2, 6) and interlace == 0
            bpp = 4 if ctype == 6 else 3
        elif kind == b"IDAT":
            idat += chunk
        pos += 12 + length
    raw, stride, prev, rows = zlib.decompress(idat), width * bpp, bytearray(width * bpp), []
    for y in range(height):
        kind, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a, b = (line[i - bpp] if i >= bpp else 0), prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if kind == 1: line[i] = (line[i] + a) & 255
            elif kind == 2: line[i] = (line[i] + b) & 255
            elif kind == 3: line[i] = (line[i] + (a + b) // 2) & 255
            elif kind == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(bytes(line))
        prev = line
    return width, height, bpp, rows


def _logo_shares(path):
    """Width, height, and the shares of the height taken by the whole mark and by the word, where the
    word is everything right of the widest empty column gap (the gap between icon and word)."""
    width, height, bpp, rows = _png_rgba_rows(path)
    seen = lambda row, x: ((row[x * bpp + 3] if bpp == 4 else 255) > 24 and sum(row[x * bpp:x * bpp + 3]) < 3 * 245)
    cols = [any(seen(row, x) for row in rows) for x in range(width)]
    gaps, start = [], None
    for x, c in enumerate(cols + [True]):
        if not c and start is None:
            start = x
        elif c and start is not None:
            gaps.append((x - start, x)); start = None
    word_from = max(g for g in gaps if g[1] < width)[1]
    mark = [y for y, row in enumerate(rows) if any(seen(row, x) for x in range(width))]
    word = [y for y, row in enumerate(rows) if any(seen(row, x) for x in range(word_from, width))]
    return width, height, (mark[-1] - mark[0] + 1) / height, (word[-1] - word[0] + 1) / height


@pytest.mark.parametrize("page", _NAV_PAGES + (_ARCH / "index.html",), ids=lambda p: str(p.relative_to(ROOT)))
def test_the_masthead_shows_the_recut_logo_at_its_true_size(page):
    assert _NAV_IMG in _nav(_read(page))


def test_the_masthead_logo_and_its_word_are_as_tall_as_9robots_ai():
    css = _shared_block(_read(_PUB / "assets/site.css"))
    assert ".nav-logo img{display:block;height:43px;" in css
    assert "@media (max-width:767px){.nav-logo img{height:39px}}" in css
    width, height, mark, word = _logo_shares(_NAV_LOGO)
    assert (width, height) == (754, 132)
    assert abs(mark - _NINEROBOTS_MARK) < 0.01, f"the mark fills {mark:.3f} of the logo, 9robots.ai's {_NINEROBOTS_MARK:.3f}"
    assert abs(word - _NINEROBOTS_WORD) < 0.01, f"the word fills {word:.3f} of the logo, 9robots.ai's {_NINEROBOTS_WORD:.3f}"


def test_the_orange_is_9robots_ai_s_orange():
    # REQ-GHA-018 clause 14, amended 2026-11-05: orange text uses 9robots.ai's orange, #E75A1E, which is
    # also the orange tile in GlassHood's logo; the blue stays 9robots.ai's blue, #0C41CD.
    site, arch = _read(_PUB / "assets/site.css"), _read(_ARCH / "styles.css")
    for css in (site, arch):
        assert "--orange:#e75a1e" in css and "--blue:#0c41cd" in css
        assert "amber" not in css.lower() and "#c87400" not in css and "#e89008" not in css
    assert ".hero-title-first{color:var(--orange)}" in site
    assert "--orange:#e75a1e" in _read(ROOT / "deploy/waking-page/index.html")


def test_the_architecture_page_uses_the_site_s_own_lato():
    # The masthead looks the same on every page (REQ-GHA-018 clause 14, amended 2026-11-05): the
    # architecture page renders it with the same font files as the site, not with Google Fonts.
    html, css = _read(_ARCH / "index.html"), _read(_ARCH / "styles.css")
    assert "fonts.googleapis.com" not in html and "fonts.gstatic.com" not in html
    for weight in ("400", "700"):
        assert f"src:url(/architecture/fonts/lato-{weight}.woff2) format('woff2')" in css
        assert (_ARCH / f"fonts/lato-{weight}.woff2").read_bytes() == (_PUB / f"assets/fonts/lato-{weight}.woff2").read_bytes()
    assert json.loads(_read(_W / "architecture/staticwebapp.config.json"))["mimeTypes"][".woff2"] == "font/woff2"


def test_the_app_entry_is_labelled_log_in_on_every_page():
    # REQ-GHA-018 clause 1, amended 2026-11-05 (third): "Log in", in the masthead and in the footer of
    # every public page; it still leads to app.glasshood.ai.
    for page in _NAV_PAGES + (_ARCH / "index.html",):
        html = _read(page)
        footer = html.split('<footer class="footer">', 1)[1].split("</footer>", 1)[0]
        assert '<a class="nav-open" href="https://app.glasshood.ai">Log in</a>' in _nav(html), page.name
        assert '<a href="https://app.glasshood.ai" class="site-footer-link">Log in</a>' in footer, page.name
        assert "Open app" not in html, page.name


def test_the_logo_is_always_shown_at_full_strength():
    # REQ-GHA-018 clause 14, amended 2026-11-05 (second): the logo in the masthead and in the footer is
    # never faded, and pointing at it does not change it.
    for css in (_read(_PUB / "assets/site.css"), _read(_ARCH / "styles.css")):
        rules = re.findall(r"([^{}]+)\{([^{}]*)\}", re.sub(r"/\*.*?\*/", "", css, flags=re.S))
        logo_rules = [(sel.strip(), body) for sel, body in rules if "nav-logo" in sel or "site-footer-brand" in sel]
        assert logo_rules
        for sel, body in logo_rules:
            assert "opacity" not in body and "filter" not in body, sel
            assert not (":hover" in sel and " img" in sel), sel


_HOME_SECTIONS = {
    "read-only": ("Read-only by design",
        "GlassHood installs nothing in the system it watches. Toward the monitored cloud project, every call is "
        "list, get or describe; nothing creates, changes or deletes anything there. Read-only is enforced twice: "
        "by that call surface, and by the identity itself, a short-lived, viewer-only federated token with no "
        "stored keys. Even a full compromise of the engine cannot write to the monitored cloud project, and there "
        "is no stored cloud key to steal."),
    "live-topology": ("Live topology against declared design",
        "Auto-discovery alone misses nodes it cannot enumerate and carries no intended state; a declarative "
        "manifest alone goes stale the moment it is written. GlassHood merges both: live discovery is overlaid "
        "with declarative YAML manifests into a single graph, rebuilt with fresh metrics every cycle. Because "
        "observed reality and declared intent sit in one model, the gap between what was designed and what is "
        "actually running is visible, and change between cycles is tracked."),
    "compliance": ("Compliance as a byproduct of observation",
        "Compliance is not a pre-baked attestation. Reports are generated on demand from what the engine actually "
        "observed (rule alerts, CVE findings and anomalies), with a per-subsystem ALCOA+ audit trail: the evidence "
        "is the observation. The reports are aligned to EU GMP Annex 11, ALCOA+ and 21 CFR Part 11 and support "
        "human review. They are unsigned and are not an independent validation or certification; a qualified "
        "person reviews and adopts every artifact."),
}


def test_home_cards_open_their_sections_as_on_the_architecture_page():
    # REQ-GHA-018 clause 14, amended 2026-11-05 (third): each card can be clicked as a whole and shows a
    # section further down on Home about its topic, in the wording Igor approved on 2026-11-05.
    home = _read(_PUB / "index.html")
    assert '<main class="pd-page">' in home and home.count('class="feature pd-card"') == 3
    hidden = home.split('<div class="pd-hidden-until-reveal">', 1)[1].split("</main>", 1)[0]
    for cid, (title, text) in _HOME_SECTIONS.items():
        assert f'<a href="#{cid}" class="feature pd-card" data-target="{cid}">' in home, cid
        section = re.search(rf'<section class="wrap home-detail" id="{cid}">(.*?)</section>', hidden, re.S)
        assert section, cid
        assert f"<h2>{title}</h2>" in section.group(1), cid
        assert " ".join(re.search(r"<p>(.*?)</p>", section.group(1), re.S).group(1).split()) == text, cid
    assert home.count("Click to read the section &rarr;") == 3
    assert home.rstrip().endswith('<script src="/architecture/app.js"></script>\n</body>\n</html>')
    css = _read(_PUB / "assets/site.css")
    assert ".pd-hidden-until-reveal{display:none}" in css
    assert ".pd-page.revealed .pd-hidden-until-reveal{display:block;" in css
    assert 'content:"Click to read the section →"' in css
    # The behaviour is the architecture page's own script, unchanged: it reveals the sections and scrolls.
    js = _read(_ARCH / "app.js")
    assert "querySelector('.pd-page')" in js and "classList.add('revealed')" in js and "scrollIntoView" in js
