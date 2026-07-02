"""Structural guards for the GlassHood architecture page (architecture/).

Static, dependency-free assertions on the served files, mirroring the TestRobin
page's guard suite — the family definition of "done" for this page shape. They
lock the 2026-07 rebuild's invariants so a later edit can't silently regress:
zone-row detail grammar, the two distinct ColdVault access paths, hover/focus
parity, accessibility roles, and the sanitized-public-page rules.
"""
import re
from pathlib import Path

_ARCH = Path(__file__).resolve().parents[1] / "architecture"
_HTML = (_ARCH / "index.html").read_text(encoding="utf-8")
_CSS = (_ARCH / "styles.css").read_text(encoding="utf-8")
_FLAT = _CSS.replace(" ", "").replace("\n", "")


def test_both_diagrams_present():
    assert "arch-diagram--overview" in _HTML
    assert "arch-diagram--detail" in _HTML


def test_overview_is_above_the_cards():
    assert _HTML.index("arch-diagram--overview") < _HTML.index('class="pd-cards"')


def test_detail_is_inside_the_reveal():
    assert _HTML.index("arch-diagram--detail") > _HTML.index("pd-hidden-until-reveal")


def test_detail_heading_present():
    assert "Detailed GlassHood topology" in _HTML


def test_one_column_9robots_standard():
    assert "--max:1120px" in _CSS
    assert "max-width:none" in _CSS
    assert ".pd-eyebrow" in _CSS


def test_detail_design_width_pin_and_contained_scroll():
    # Uniform min-height boxes spill below the 1070px design width; the pin keeps the
    # composition intact and narrow viewports get a contained scroll. Scoped to .arch-flow
    # so the legend stays fluid (deliberate improvement over the broader >div selector).
    assert re.search(r"\.arch-diagram--detail\s*\{[^}]*overflow-x\s*:\s*auto", _CSS)
    assert re.search(r"\.arch-diagram--detail\s+\.arch-flow\s*\{[^}]*min-width\s*:\s*1070px", _CSS)


def test_keyboard_focus_parity_and_outline():
    for sel in ("a.cv-link:focus-visible", ".cv-html-link:focus-visible"):
        assert sel.replace("a.cv-link", ".cv-link") in _CSS or sel in _CSS, f"missing {sel}"
    assert "outline:2pxsolid#e75a1e" in _FLAT, "explicit focus outline must not be removed"


def test_overview_cta_single_text_node():
    m = re.search(r'<g class="cv-hover-btn">(.*?)</g>', _HTML, re.DOTALL)
    assert m and "<text" not in m.group(1), "cv-hover-btn must stay rect-only"
    assert _HTML.count('class="cv-cta"') == 1
    assert _HTML.index('class="cv-hover-btn"') < _HTML.index('class="cv-cta"'), \
        "pill rect must precede the CTA text (SVG paint order)"


def test_detail_cta_single_text_node():
    assert _HTML.count('class="cv-cta-html"') == 1
    assert ".cv-cta-html::before{" in _FLAT, "hover pill ::before must not be removed"


def test_hover_matches_hero_card_treatment():
    assert "translateY(-2px)" in _CSS
    assert "filter:drop-shadow(06px20pxrgba(0,0,0,.06))" in _FLAT
    assert "box-shadow:06px20pxrgba(0,0,0,.06)" in _FLAT
    assert "vector-effect:non-scaling-stroke" in _FLAT, "1px hover border must stay scale-independent"
    assert "stroke-width:2" not in _FLAT, "the old thicker-on-hover stroke bump must not return"


def test_cta_resting_contrast():
    # #6e7582 passes WCAG AA (4.6:1) on white; the old #7a818c (3.9:1) failed.
    assert re.search(r"\.cv-cta\{fill:#6e7582", _FLAT)
    assert re.search(r"\.cv-cta-html\{color:#6e7582", _FLAT)


def test_coldvault_links_hygiene():
    for cls in ("cv-link", "cv-html-link"):
        m = re.search(rf'<a class="{cls}"[^>]*>', _HTML)
        assert m, f"{cls} anchor missing"
        assert 'target="_blank"' in m.group(0) and 'rel="noopener noreferrer"' in m.group(0)
        assert "architecture.coldvault.ai" in m.group(0)


def test_no_nameless_tab_stops():
    # Neither ColdVault link may sit inside an aria-hidden subtree (WCAG: no nameless focusable).
    for cls in ("cv-link", "cv-html-link"):
        link_at = _HTML.index(f'<a class="{cls}"')
        stack = []
        for m in re.finditer(r'<(div|svg)\b[^>]*>|</(?:div|svg)>', _HTML[:link_at]):
            if m.group(0).startswith("</"):
                if stack: stack.pop()
            elif not m.group(0).endswith("/>"):
                stack.append(m.group(0))
        assert all('aria-hidden="true"' not in t for t in stack), f"{cls} inside aria-hidden subtree"


def test_diagram_roles():
    # Both containers hold a live link, so role=img (non-interactive subtree) is wrong everywhere.
    assert re.search(r'<svg[^>]*viewBox="0 8 800 248"[^>]*role="group"[^>]*aria-label="High-level:', _HTML)
    assert re.search(r'arch-diagram--detail" role="group" aria-label="Detailed topology:', _HTML)
    assert 'role="img"' not in _HTML, "no role=img wrappers on this page (live links inside)"


def test_two_access_paths_stay_distinct():
    # GlassHood's content-accuracy invariant: keyless WIF reads vs API-key narrative,
    # visually and textually distinct in BOTH diagrams.
    assert "KEYLESS" in _HTML and "API KEY" in _HTML
    assert ">keyless<" in _HTML and ">API key<" in _HTML, "overview needs both labeled paths"
    assert _HTML.count("0d7d8a") >= 4, "the teal trust accent must survive"


def test_keyless_readonly_claims_consistent():
    low = _HTML.lower()
    assert "no stored keys" in low and "read-only" in low
    assert "short-lived" in low


def test_no_internal_identifiers_leak():
    low = _HTML.lower()
    for needle in ("acrglasshood", "rg-glasshood", "kv-glasshood", "nr-411", "nr-94n",
                   "azurecr.io", ".azurewebsites.", "subscription"):
        assert needle not in low, f"internal identifier on the public page: {needle}"
    # the federation sample stays sanitized placeholders
    assert "PROJECT_NUMBER" in _HTML and "POOL_ID" in _HTML and "SA_EMAIL" in _HTML


def test_no_design_tool_artifacts():
    assert "{{" not in _HTML
    assert "var(--font-sans)" not in _HTML


def test_no_planned_nodes():
    assert "PLANNED" not in _HTML


def test_no_svg_arrow_markers():
    assert "marker-end" not in _HTML and "<marker" not in _HTML, \
        "family standard: plain lines / text glyph arrows, no SVG markers"


def test_cards_map_to_real_sections():
    targets = re.findall(r'class="pd-card" data-target="([a-z-]+)"', _HTML)
    ids = set(re.findall(r'<section class="pd-section" id="([a-z-]+)"', _HTML))
    assert len(targets) == 2 and all(t in ids for t in targets)


def test_launch_cta_present():
    assert re.search(r'<a href="https://glasshood.ai/demo" class="button"', _HTML)


def test_noindex_and_title():
    assert 'content="noindex, nofollow"' in _HTML
    assert "<title>Architecture - GlassHood</title>" in _HTML


def test_lock_icon_trap_css():
    assert re.search(r"\.arch-diagram--detail\s+svg\s*\{[^}]*width\s*:\s*auto", _CSS), \
        "inline lock icons must not inherit full-width svg sizing (the lock-icon blowup trap)"
