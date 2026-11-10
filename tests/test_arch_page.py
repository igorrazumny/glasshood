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
    # GlassHood's content-accuracy invariant: keyless WIF reads vs anonymous MCP checks of
    # coldvault.ai (REQ-GHA-020 clause 8; the API-key path went with the old platform),
    # visually and textually distinct in BOTH diagrams.
    assert "KEYLESS" in _HTML and "MCP &#183; NO KEY" in _HTML
    assert ">keyless<" in _HTML and ">MCP<" in _HTML, "overview needs both labeled paths"
    assert "API KEY" not in _HTML and "API key" not in _HTML, "no API-key path is left"
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
    assert targets == ["dashboard", "implementation", "zero-trust", "mcp"] and all(t in ids for t in targets)
    assert 'id="compliance"' in _HTML, "the compliance section stays, without a top card"


def test_launch_cta_present():
    assert re.search(r'<a href="https://app.glasshood.ai/demo" class="button"', _HTML)


def test_the_page_shows_how_glasshood_is_reached_today():
    # REQ-GHA-018 clause 2, amended 2026-11-05 (fifth): the React app and the waking page are served at
    # app.glasshood.ai by an Azure Static Web App; the API runs on Container Apps behind its managed TLS
    # ingress; links into the app go to app.glasshood.ai, and glasshood.ai is not named as the app's address.
    detail = _HTML.split("arch-diagram--detail", 1)[1]
    assert ">Static Web App</span>" in detail and "app.glasshood.ai &#183; React 18 SPA &#183; waking page" in detail
    assert "Container Apps &#183; TLS &#183; API" in detail and "TLS &#183; glasshood.ai" not in _HTML
    assert _HTML.count(">React 18 SPA<") == 0 and _HTML.count("React 18 SPA") == 1, "the React app sits on the Static Web App only"
    assert "an Azure Static Web App for the React app at app.glasshood.ai" in _HTML
    assert "reach GlassHood's API on Azure Container Apps through managed TLS ingress" in _HTML
    for href in re.findall(r'href="(https://glasshood\.ai/[^"]*)"', _HTML):
        assert href in ("https://glasshood.ai/", "https://glasshood.ai/architecture/", "https://glasshood.ai/contact/", "https://glasshood.ai/demo"), href


def test_indexable_and_title():
    # REQ-GHA-018, sixth amendment of 2026-11-10: the page is indexable, with its canonical address.
    assert "noindex" not in _HTML
    assert '<link rel="canonical" href="https://glasshood.ai/architecture/">' in _HTML
    assert "<title>Architecture - GlassHood</title>" in _HTML


def test_lock_icon_trap_css():
    assert re.search(r"\.arch-diagram--detail\s+svg\s*\{[^}]*width\s*:\s*auto", _CSS), \
        "inline lock icons must not inherit full-width svg sizing (the lock-icon blowup trap)"


def test_zero_trust_mcp_and_current_facts():
    # The zero-trust and MCP sections, the MCP server in the detail diagram, and only facts that hold today.
    for needle in ('id="zero-trust"', 'id="mcp"', "Verify explicitly", "Least privilege", "Assume breach",
                   "<code>get_topology</code>", "<code>get_impact_analysis</code>", "<code>get_node_logs</code>",
                   ">MCP server</span>", "AI agents through a local MCP server"):
        assert needle in _HTML, needle
    low = _HTML.lower()
    assert "idle timeout" not in low, "sessions renew silently today: no idle-timeout claim"
    assert "auth0 sso + local fallback" not in low and "acr &#183;" not in low


def test_glasshood_is_an_mcp_client_of_coldvault_next_to_its_own_mcp_server():
    # REQ-GHA-020 clause 8: GlassHood as an MCP client of ColdVault, next to its own MCP server.
    section = _HTML[_HTML.index('id="mcp"'):]
    section = section[:section.index("</section>")]
    for needle in ("GlassHood as an MCP client", "<code>verify_attestation</code>", "fresh nonce",
                   "Recheck via MCP", "never call <code>ask</code>", "no key"):
        assert needle in section, needle
    assert ">MCP server</span>" in _HTML, "its own MCP server stays in the detail diagram"


def test_the_implementation_rows_stack_on_phones():
    # Sati's warning on #44: at 320 px the Host line's "app.glasshood.ai" widened the page by 22 px. On phones
    # each label sits above its value, so no row is wider than the screen.
    css = (_ARCH / "styles.css").read_text(encoding="utf-8")
    assert "@media(max-width:480px){.impl-item{flex-direction:column;gap:2px}.impl-item>strong{flex:none}}" in css


def _flat_text():
    import html as _html
    return " ".join(_html.unescape(re.sub(r"<[^>]+>", " ", _HTML)).split())


def test_the_ai_is_described_as_it_runs_today():
    # REQ-GHA-018, amended 2026-11-07: the AI overviews (REQ-GHA-024), the AI log review that raises its own,
    # labelled alarms (REQ-GHA-029) and Investigate deeper, in the wording Igor approved; no model is named, the
    # switched-off Platform API is gone, and nothing says the AI never raises an alarm.
    flat = _flat_text()
    for needle in ("an AI layer then summarizes the state and reviews the logs",
                   "every AI alarm quotes the log lines it rests on, so a person can check it",
                   "a model on Vertex AI, in the monitored Google Cloud project",
                   "raises its own alarms, a separate kind labelled as found by AI review",
                   "may search the web for the error, and writes a report with an executive summary",
                   "the AI prompts are generic", "Deterministic first · AI on top", "AI layer overviews, log review"):
        assert needle in flat, needle
    for gone in ("never originates", "narrates on top", "explains only", "produces every signal", "Platform API",
                 "inference-as-a-service", "prompt profile", "target-tuned", "never raises an alert", "Gemini", "Flash-Lite"):
        assert gone not in flat, gone
    assert "with an AI layer on top that writes the overviews and reviews the logs, raising its own labelled alarms" in _HTML


def test_glasshood_reads_coldvault_metrics_with_its_own_token():
    # REQ-GHA-018, amended 2026-11-07 (REQ-GHA-025): ColdVault's metrics with a one-hour identity token of its own and
    # no key; no ids, account names or addresses of the identity chain on the page.
    flat = _flat_text()
    assert "its metrics with a one-hour identity token of GlassHood’s own (below)" in flat
    assert "ColdVault’s own metrics. Every 10 minutes GlassHood also reads coldvault.ai/api/metrics" in flat
    assert "GlassHood holds no key or password for ColdVault" in flat
    assert "health · metrics with a one-hour token · MCP: verify_attestation every 10 min" in flat
    assert _HTML.count("reads ColdVault's metrics with a one-hour identity token of its own") == 2, "both diagram descriptions"
    assert "(30 s)" not in flat and "health/metrics API" not in flat
    for leak in ("glasshood-coldvault", "glasshood-azure-pool", "braintransplant", "iam.gserviceaccount.com"):
        assert leak not in _HTML.lower(), leak


def test_the_collection_cadences_are_the_ones_that_run():
    # REQ-GHA-018, amended 2026-11-07 (second): one shared 10-minute interval for every collector (REQ-GHA-016);
    # the AI overview and the AI log review every 3 hours.
    sec = _HTML.split('<section class="pd-section" id="collection">', 1)[1].split("</section>", 1)[0]
    assert "(60&nbsp;s)" not in sec and "(~5&nbsp;min)" not in sec and "(30&nbsp;s)" not in sec
    assert sec.count("every 10&nbsp;minutes") == 4
    assert "Every collector runs on one shared 10-minute interval" in " ".join(sec.split())
    assert "the AI overview and the AI log review run every 3 hours" in " ".join(sec.split())


def test_the_page_leads_with_ai_monitoring_for_business_and_it():
    # REQ-GHA-018, amended 2026-11-07 (third and fourth), Igor's direction: AI monitoring that shows business and IT
    # where the system and each component stand, not a check against a declared design, described as delivered to a
    # customer: alerts to the distribution lists by severity, tickets in the ticketing system and regular updates.
    flat = _flat_text()
    hero = " ".join(_HTML.split('<p class="pd-hero">', 1)[1].split("</p>", 1)[0].split())
    assert hero == ("GlassHood is AI monitoring for integration pipelines and complex systems. Read-only collectors bring in "
                    "the logs and measurements of every component, deterministic checks run first and AI on top, and one "
                    "dashboard shows business and IT where the system and each component stand.")
    overview = _HTML.split("arch-diagram--overview", 1)[1].split("</svg>", 1)[0]
    for label in (">Business &amp; IT<", ">dashboard &#183; alerts &#183; logs<", ">Landscape file<",
                  ">components &#183; logs &#183; alarms<", ">Alerts &amp; tickets<", ">lists &#183; ServiceNow<",
                  ">regular updates<", ">live &#8853; landscape file<"):
        assert label in overview, label
    for gone in (">Declared design<", ">User<", "evidence report", "regulated systems"):
        assert gone not in overview, gone
    assert "regulated systems" not in _HTML and "reconciled against declared design" not in _HTML
    sec = " ".join(_HTML.split('<section class="pd-section" id="dashboard">', 1)[1].split("</section>", 1)[0].split())
    for needle in ("Business owners and IT teams read the same dashboard", "Each component&rsquo;s logs are one click away",
                   "Every alert carries a severity: critical, warning or info",
                   "GlassHood sends each alert by e-mail to the lists set for its severity",
                   "opens an incident for each new critical or warning alert", "set up for each deployment",
                   "<strong>Regular updates, as agreed.</strong>",
                   "the system&rsquo;s status, the open tickets and who is working on them"):
        assert needle in sec, needle
    low = _HTML.lower()
    for gone in ("not built", "built yet", "does not send them out", "the live demo has none", "next:", "parked"):
        assert gone not in low, gone
    order = [_HTML.index(f'<section class="pd-section" id="{i}">') for i in ("analysis", "dashboard", "topology")]
    assert order == sorted(order), "the dashboard section follows the analysis"
    assert "Alerts &amp; tickets</div>" in _HTML.split("arch-diagram--detail", 1)[1], "the detailed diagram shows it too"
    assert "alerts to the distribution lists by severity, tickets in the customer&rsquo;s ticketing system and regular updates" in _HTML
    assert "the dashboard, alerts, tickets and regular updates for business and IT" in flat
    assert "or single sign-on through Auth0" in _HTML
