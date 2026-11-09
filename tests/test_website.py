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


def test_both_hosts_revalidate_everything_but_the_fonts_and_send_security_headers():
    # Pages, styles and scripts are revalidated on every load; the two Lato files never change under their names, so
    # they are kept by the browser for a year (clause 14, amended 2026-11-09: Lato from the first paint).
    for cfg_path, font_routes in ((_PUB / "staticwebapp.config.json", ("/assets/fonts/*", "/architecture/fonts/*")),
                                  (_W / "architecture/staticwebapp.config.json", ("/architecture/fonts/*",))):
        cfg = json.loads(_read(cfg_path))
        headers = cfg["globalHeaders"]
        assert headers["Cache-Control"] == "no-cache, must-revalidate", cfg_path
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert "Referrer-Policy" in headers and "X-Frame-Options" in headers
        assert cfg["responseOverrides"]["404"]["rewrite"] == "/404.html"
        routes = {r["route"]: r for r in cfg["routes"]}
        for route in font_routes:
            assert routes[route] == {"route": route, "headers": {"Cache-Control": "public, max-age=31536000, immutable"}}, (cfg_path, route)
        assert json.dumps(cfg).count("immutable") == len(font_routes), cfg_path


def test_lato_from_the_first_paint():
    # Clause 14, amended 2026-11-09: both Lato weights are preloaded before the stylesheet on every page, declared with
    # font-display optional (a page view has Lato at first paint or keeps the system font, never a swap), on the site
    # and on the architecture page.
    for page in _NAV_PAGES:
        html = _read(page)
        for weight in ("400", "700"):
            assert f'<link rel="preload" href="/assets/fonts/lato-{weight}.woff2" as="font" type="font/woff2" crossorigin>' in html, page
        assert html.index("lato-700.woff2") < html.index('rel="stylesheet"'), page
    arch = _read(_ARCH / "index.html")
    for weight in ("400", "700"):
        assert f'<link rel="preload" href="/architecture/fonts/lato-{weight}.woff2" as="font" type="font/woff2" crossorigin>' in arch
    assert arch.index("lato-700.woff2") < arch.index('rel="stylesheet"') and 'href="/architecture/styles.css?v=29"' in arch
    for css, folder in ((_read(_PUB / "assets/site.css"), "/assets/fonts"), (_read(_ARCH / "styles.css"), "/architecture/fonts")):
        for weight in ("400", "700"):
            assert f"font-weight:{weight};font-display:optional;\n  src:url({folder}/lato-{weight}.woff2) format('woff2')" in css, (folder, weight)
        assert "font-display:swap" not in css


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
    # REQ-GHA-018 clauses 1 and 14, amended 2026-11-07 (third): the hero says what GlassHood is, as in Igor's summary.
    assert ('<h1 class="hero-title"><span class="hero-title-first">AI monitoring for integration pipelines</span> '
            '<span class="hero-title-rest">and complex systems</span></h1>') in home
    hero = " ".join(home.split('<p class="hero-text">', 1)[1].split("</p>", 1)[0].split())
    assert hero == ("GlassHood shows business and IT where an integration pipeline or other complex system stands, end to end "
                    "and down to each component. AI reads the logs of every component, and a dashboard shows the state of the "
                    "whole system and of each part, with its logs one click away. GlassHood installs nothing in the systems it "
                    "watches and only reads them.")
    # No colour wash behind the hero (Igor, 2026-11-05: "fade out, we will remove for GlassHood").
    assert "hero-wash" not in home and "hero-wash" not in _read(_PUB / "assets/site.css")
    # Home's cards carry no icon (REQ-GHA-018, fifth amendment of 2026-11-07: "I just do not see a point in this graphics").
    cards = home.split('<section class="wrap features"', 1)[1].split("</section>", 1)[0]
    assert "feature-icon" not in home and "<svg" not in cards and cards.count('class="feature pd-card"') == 3


def test_contact_has_labels_and_marks_the_required_fields():
    html = _read(_PUB / "contact/index.html")
    for field in ("contact-name", "contact-email", "contact-message"):
        assert f'<label for="{field}" class="form-label form-label-required">' in html, field
    assert "Required fields" in html and '<div class="form-row">' in html
    css = _read(_PUB / "assets/site.css")
    assert '.form-label-required::after{content:" *"' in css


# The masthead logo is the designer's GlassHood logo, sized so that its icon is as tall as the icon in 9robots.ai's
# masthead logo (REQ-GHA-018 clause 14, amended 2026-11-06). 9robots.ai sizes its logo 43 px, and 39 px below
# 768 px (Tailwind's max-[768px] in 9robots-site next/components/Nav.tsx). In its image, /img/9robots-logo.png
# (4535 x 982), the icon covers rows 29 to 971 at half coverage: 943/982 of the height, starting at 29/982.
# GlassHood's masthead image is the designer's logo (architecture/img/glasshood-logo.png), only scaled, so that
# its icon has the same share and place; the word keeps the designer's proportions and is smaller than "9robots".
_NAV_LOGO = ROOT / "architecture/img/glasshood-logo-nav.png"
_DESIGNER_LOGO = ROOT / "architecture/img/glasshood-logo.png"
_NAV_IMG = '<img src="/architecture/img/glasshood-logo-nav.png" alt="GlassHood" width="581" height="132">'
_NINEROBOTS_ICON, _NINEROBOTS_ICON_TOP = 943 / 982, 29 / 982


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


def _logo_rows(path):
    """Width, height, and the first and last rows of the icon and of the word at half coverage (alpha at least
    128 and not near-white, the usual edge of a smoothed shape), the word being everything right of the widest
    empty column gap, which separates it from the icon."""
    width, height, bpp, rows = _png_rgba_rows(path)
    seen = lambda row, x: ((row[x * bpp + 3] if bpp == 4 else 255) >= 128 and sum(row[x * bpp:x * bpp + 3]) < 3 * 245)
    cols = [any(seen(row, x) for row in rows) for x in range(width)]
    gaps, start = [], None
    for x, c in enumerate(cols + [True]):
        if not c and start is None:
            start = x
        elif c and start is not None:
            gaps.append((x - start, x)); start = None
    word_from = max(g for g in gaps if g[1] < width)[1]
    icon = [y for y, row in enumerate(rows) if any(seen(row, x) for x in range(word_from))]
    word = [y for y, row in enumerate(rows) if any(seen(row, x) for x in range(word_from, width))]
    return width, height, (icon[0], icon[-1]), (word[0], word[-1])


@pytest.mark.parametrize("page", _NAV_PAGES + (_ARCH / "index.html",), ids=lambda p: str(p.relative_to(ROOT)))
def test_the_masthead_shows_the_designers_logo_at_its_true_size(page):
    assert _NAV_IMG in _nav(_read(page))


def test_the_masthead_logo_is_the_designers_with_its_icon_as_tall_as_9robots_ai():
    css = _shared_block(_read(_PUB / "assets/site.css"))
    assert ".nav-logo img{display:block;height:43px;" in css
    assert "@media (max-width:767px){.nav-logo img{height:39px}}" in css
    width, height, icon, word = _logo_rows(_NAV_LOGO)
    assert (width, height) == (581, 132)
    ih = icon[1] - icon[0] + 1
    assert abs(ih / height - _NINEROBOTS_ICON) < 0.005, f"the icon fills {ih / height:.4f} of the logo, 9robots.ai's {_NINEROBOTS_ICON:.4f}"
    assert abs(icon[0] / height - _NINEROBOTS_ICON_TOP) < 0.005, "the icon starts where 9robots.ai's does"
    # The designer's proportions: the word's height and place against the icon, and the logo's width.
    dw, dh, dicon, dword = _logo_rows(_DESIGNER_LOGO)
    dih = dicon[1] - dicon[0] + 1
    assert abs((word[1] - word[0] + 1) / ih - (dword[1] - dword[0] + 1) / dih) < 0.01, "the word keeps the designer's height"
    assert abs((word[0] - icon[0]) / ih - (dword[0] - dicon[0]) / dih) < 0.01, "the word keeps the designer's place"
    assert abs((width / ih) / (dw / dih) - 1) < 0.01, "the logo is neither stretched nor squeezed"


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


# REQ-GHA-018 clauses 1 and 14, amended 2026-11-07 (third and fourth): Home in the direction of Igor's one-page summary
# of 2026-11-07, AI monitoring that shows business and IT where the system and each component stand, described as
# delivered to a customer (no live, planned or next labels).
# REQ-GHA-018, fifth amendment of 2026-11-07: How it works lists the four points of Igor's deck "9robots Overview and
# Products" of 2026-11-07, word for word (Home is the short version; the longer texts are on 9robots.ai's GlassHood page).
_HOW_IT_WORKS_POINTS = [
    "AI reads the logs of every component in an integration pipeline or other complex system.",
    "A dashboard shows where the system and each component stand, with direct access to every log.",
    "Alerts the right distribution lists by severity and opens tickets in your ticketing system (e.g. ServiceNow).",
    "Sends regular updates as agreed: system status, open tickets and who is working on them, with links.",
]

_HOME_CARDS = {
    "what-it-is": ("What it is",
        "AI monitoring and dashboard services for business and IT, down to each component.",
        "GlassHood is AI monitoring with dashboards, for business and IT alike. It connects to a running integration "
        "pipeline or other complex system and shows where the whole "
        "system and each of its components stand, live. Rules and anomaly detection raise alerts from the measurements, and "
        "every 3 hours an AI review reads each component's logs and raises its own alarms, labelled as found by the AI "
        "review. A short AI overview says in plain words how the whole system is doing and what needs attention, and each "
        "component has its own. Business owners and IT teams look at the same dashboard, and nothing they do there changes "
        "the monitored system."),
    "the-problem": ("The pain it solves",
        "Business owners lack a shared, end-to-end view of integration pipelines and complex systems' health.",
        "With current tools, business owners cannot see where their system stands, end to end. An integration pipeline runs "
        "through many systems, and each is watched by its own team with its own tool, in its own technical terms. When a "
        "connection stops or a message no longer arrives, the first sign is often a wrong result further down the chain, "
        "and the business owner learns of it late and second-hand. GlassHood puts the whole chain in one view that business "
        "and IT read together, down to each component, and points at the part where it breaks."),
    "how-it-works": ("How it works",
        "AI reads the logs of every component, a dashboard shows where the system and each component stand, and alerts, "
        "tickets and regular updates reach the right people.",
        None),
}


def test_home_answers_what_it_is_the_problem_it_solves_and_how_it_works():
    # Each card can be clicked as a whole and shows the sections further down on Home, as on the architecture page.
    # How it works lists the four points of Igor's deck: the logs, the dashboard, alerts and tickets, regular updates.
    import html as _html
    norm = lambda t: " ".join(_html.unescape(t).split())
    home = _read(_PUB / "index.html")
    assert '<main class="pd-page">' in home and home.count('class="feature pd-card"') == 3
    order = [home.index(f'<a href="#{cid}" class="feature pd-card" data-target="{cid}">') for cid in _HOME_CARDS]
    assert order == sorted(order), "What it is, then The pain it solves, then How it works"
    hidden = home.split('<div class="pd-hidden-until-reveal">', 1)[1].split("</main>", 1)[0]
    for cid, (title, text, detail) in _HOME_CARDS.items():
        card = home[home.index(f'data-target="{cid}">'):]
        assert f'<h2 class="feature-title">{title}</h2>' in card[:2000], cid
        assert norm(card.split('<p class="feature-text">', 1)[1].split("</p>", 1)[0]) == text, cid
        section = re.search(rf'<section class="wrap home-detail" id="{cid}">(.*?)</section>', hidden, re.S)
        assert section and f"<h2>{title}</h2>" in section.group(1), cid
        if detail:
            assert norm(re.search(r"<p>(.*?)</p>", section.group(1), re.S).group(1)) == detail, cid
    how = re.search(r'<section class="wrap home-detail" id="how-it-works">(.*?)</section>', hidden, re.S).group(1)
    assert [norm(li) for li in re.findall(r"<li>(.*?)</li>", how, re.S)] == _HOW_IT_WORKS_POINTS
    assert "<h3>" not in how
    assert '<a class="button" href="/architecture/">See the architecture &rarr;</a>' in how
    assert "Where we are today" not in home and "system description" not in home.lower()
    # Not a check against a declared design, nor compliance documentation (Igor, 2026-11-07).
    for gone in ("declared design", "design on paper", "compliance", "annex 11", "cross-cloud ai infrastructure",
                 "next:", "not built", "the live demo has none"):
        assert gone not in home.lower(), gone
    assert home.count("Click to read the section &rarr;") == 3
    assert home.rstrip().endswith('<script src="/architecture/app.js"></script>\n</body>\n</html>')
    css = _read(_PUB / "assets/site.css")
    assert ".pd-hidden-until-reveal{display:block;padding-bottom:96px}" in css  # sections visible on load (2026-11-08)
    assert ".pd-hidden-until-reveal{display:none}" not in css
    assert 'content:"Click to read the section →"' in css
    # The behaviour is the architecture page's own script, unchanged: it reveals the sections and scrolls.
    js = _read(_ARCH / "app.js")
    assert "querySelector('.pd-page')" in js and "classList.add('revealed')" in js and "scrollIntoView" in js


def test_the_top_cards_turn_glasshood_blue_when_pointed_at():
    # REQ-GHA-018 clause 14, amended 2026-11-05 (fourth): on Home and on the architecture page a card that is
    # pointed at uses GlassHood's blue, #0C41CD, for its border and its "Click to read the section" label,
    # like the buttons.
    for css in (_read(_PUB / "assets/site.css"), _read(_ARCH / "styles.css")):
        assert "--blue:#0c41cd" in css
        assert ".pd-card:hover{transform:translateY(-2px);box-shadow:0 6px 20px rgba(0,0,0,.06);border-color:var(--blue)}" in css
        assert re.search(r"\.pd-card-overlay-text\{[^}]*background:var\(--blue\)", css)
        rules = re.findall(r"([^{}]+)\{([^{}]*)\}", re.sub(r"/\*.*?\*/", "", css, flags=re.S))
        card_rules = [body for sel, body in rules if "pd-card" in sel]
        assert card_rules and not any("orange" in body for body in card_rules)


_TAGLINE = "AI monitoring for integration pipelines and complex systems"


@pytest.mark.parametrize("page", _NAV_PAGES + (_ARCH / "index.html",), ids=lambda p: str(p.relative_to(ROOT)))
def test_every_footer_says_what_glasshood_is(page):
    # REQ-GHA-018, amended 2026-11-07 (third): the footer line of every page names GlassHood's direction.
    html = _read(page)
    brand = html.split('<div class="site-footer-brand">', 1)[1].split("</div>", 1)[0]
    assert f"<p>{_TAGLINE}</p>" in brand
    assert "Cross-Cloud AI Infrastructure Monitoring" not in html


def test_home_title_and_description_say_what_glasshood_is():
    # REQ-GHA-018, amended 2026-11-07 (third): Home's title and description say the same as the footer line.
    home = _read(_PUB / "index.html")
    assert f"<title>GlassHood — {_TAGLINE}</title>" in home
    assert f'<meta property="og:title" content="GlassHood — {_TAGLINE}">' in home
    desc = re.search(r'<meta name="description" content="([^"]+)">', home).group(1)
    assert desc == f"{_TAGLINE}: dashboard services for business and IT, down to each component."
    assert f'<meta property="og:description" content="{desc}">' in home


_STATUS = "Live and operational: try it at glasshood.ai/demo"
_ONE_STACK_LIMITS = ("today a solution on Google Cloud", "different target", "writing new collectors",
                     "In this use case")


def _text(page):
    import html as _html
    return " ".join(_html.unescape(re.sub(r"<[^>]+>", "", page)).split())


def test_home_shows_where_we_are_above_the_cards():
    home = _read(_PUB / "index.html")
    section = re.search(r'<section class="wrap home-detail" id="where-we-are">(.*?)</section>', home, re.S).group(1)
    assert "<h2>Where we are</h2>" in section and _STATUS in _text(section)
    assert '<a href="https://glasshood.ai/demo">glasshood.ai/demo</a>' in section
    assert home.index('id="where-we-are"') < home.index('<section class="wrap features"')
    assert home.index('id="where-we-are"') < home.index("pd-hidden-until-reveal")


def test_architecture_shows_where_we_are():
    arch = _read(_ARCH / "index.html")
    status = arch.split('<p class="pd-hero"><strong>Where we are.</strong>', 1)[1].split("</p>", 1)[0]
    assert _STATUS in _text(status)


def test_the_heading_is_the_product_line():
    assert _TAGLINE in _text(re.search(r"<h1.*?</h1>", _read(_PUB / "index.html"), re.S).group(0))


@pytest.mark.parametrize("page", (_PUB / "index.html", _ARCH / "index.html"), ids=("home", "architecture"))
def test_no_page_limits_glasshood_to_one_cloud_or_stack(page):
    text = _text(_read(page))
    for limit in _ONE_STACK_LIMITS:
        assert limit not in text, limit
