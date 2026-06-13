# File: tests/test_theme_tokens.py
# Purpose: Structural guards for REQ-005 — the theme tokens that drive the
# light-on-cream dashboard aesthetic must NOT regress to dark navy values.
# Automated counterparts to TC-REQ-005-01 and TC-REQ-005-02.

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TAILWIND_CONFIG = REPO / "frontend" / "tailwind.config.js"
INDEX_CSS = REPO / "frontend" / "src" / "index.css"
TOPOLOGY_MAP = REPO / "frontend" / "src" / "components" / "TopologyMap.jsx"
TOPOLOGY_NODE = REPO / "frontend" / "src" / "components" / "TopologyNode.jsx"


# Hex values that signaled the old dark theme as TAILWIND TOKENS (panel /
# canvas / border surfaces — anywhere they'd paint a large area dark). The
# light-theme body intentionally uses #1f2937 as TEXT color in index.css, so
# this blacklist is applied only to tailwind.config.js where these literals
# can only mean a dark surface, not text on a light background.
DARK_THEME_LEAKS = {"#0a0e17", "#111827", "#1f2937"}


class TestTailwindTokens:
    """TC-REQ-005-01: theme tokens are light, not the old dark navy."""

    def test_surface_card_border_are_light(self):
        text = TAILWIND_CONFIG.read_text()
        # Each token line must reference a light hex
        assert "surface: '#f8fafc'" in text, (
            "REQ-005: tailwind surface must flip to the cream canvas (#f8fafc)"
        )
        assert "card: '#ffffff'" in text, (
            "REQ-005: tailwind card must flip to white (#ffffff)"
        )
        assert "border: '#e2e8f0'" in text, (
            "REQ-005: tailwind border must flip to soft slate (#e2e8f0)"
        )

    def test_no_dark_navy_in_tailwind_config(self):
        text = TAILWIND_CONFIG.read_text()
        for hex_color in DARK_THEME_LEAKS:
            assert hex_color not in text, (
                f"REQ-005 regression: dark hex {hex_color!r} reappeared in tailwind.config.js"
            )


class TestBodyAndScrollbar:
    """TC-REQ-005-02: body uses dark text on light bg; scrollbars softened."""

    def test_body_background_is_light(self):
        text = INDEX_CSS.read_text()
        assert "background-color: #f8fafc" in text, (
            "REQ-005: body must declare a light background-color (#f8fafc)"
        )

    def test_body_text_is_dark(self):
        text = INDEX_CSS.read_text()
        # Dark slate text — not the previous #e5e7eb (light gray for dark mode).
        assert "color: #1f2937" in text, (
            "REQ-005: body text color must flip to dark slate (#1f2937)"
        )
        assert "color: #e5e7eb" not in text, (
            "REQ-005 regression: dark-mode body text color #e5e7eb reappeared"
        )

    def test_scrollbars_use_slate_palette(self):
        text = INDEX_CSS.read_text()
        # New slate scrollbar tones; old dark ones gone.
        assert "background: #cbd5e1" in text, (
            "REQ-005: scrollbar thumb should be slate-300 (#cbd5e1) on light bg"
        )
        assert "background: #374151" not in text, (
            "REQ-005 regression: dark-mode scrollbar thumb #374151 reappeared"
        )


class TestTopologyPaletteConstants:
    """Structural guard so a future edit can't silently drift the topology
    accent colors back to dark-mode tones. Post-Phase 4b the constants
    read CSS vars; hexes are anchored in CANVAS_PALETTE_HEX_REFERENCE
    inside TopologyMap and in index.css :root."""

    def test_cv_accent_is_royal_blue(self):
        text = TOPOLOGY_MAP.read_text()
        assert "const CV_ACCENT = 'var(--canvas-accent-primary)'" in text, (
            "REQ-009 Phase 4b: CV_ACCENT must read --canvas-accent-primary var"
        )
        css = INDEX_CSS.read_text()
        assert "--canvas-accent-primary: #2563eb" in css, (
            "REQ-005: :root --canvas-accent-primary must be royal blue #2563eb"
        )

    def test_partner_color_is_green(self):
        text = TOPOLOGY_MAP.read_text()
        assert "const PARTNER_COLOR = 'var(--canvas-accent-partner)'" in text, (
            "REQ-009 Phase 4b: PARTNER_COLOR must read --canvas-accent-partner var"
        )
        css = INDEX_CSS.read_text()
        assert "--canvas-accent-partner: #65a30d" in css, (
            "REQ-005: :root --canvas-accent-partner must be Solace green #65a30d"
        )

    def test_planned_color_is_slate(self):
        text = TOPOLOGY_MAP.read_text()
        assert "const PLANNED_COLOR = 'var(--canvas-accent-planned)'" in text, (
            "REQ-009 Phase 4b: PLANNED_COLOR must read --canvas-accent-planned var"
        )
        css = INDEX_CSS.read_text()
        assert "--canvas-accent-planned: #94a3b8" in css, (
            "REQ-005: :root --canvas-accent-planned must be slate-400 #94a3b8"
        )


class TestTopologyNodeIsLight:
    """REQ-006: SVG node cards in TopologyNode flipped from dark navy to
    light cards. Structural grep guards against a regression to the old
    `#0f172a` / `#111827` fills or `#d1d5db` / `#e5e7eb` light-on-dark text."""

    def test_node_background_uses_computed_card_fill(self):
        """REQ-006 + REQ-008 + REQ-009 Phase 4: top-level node rect resolves
        its fill via the computed `cardFill`. The actual hex defaults now
        live in index.css :root — runtime reads var(--node-fill) and
        var(--node-fill-selected)."""
        text = TOPOLOGY_NODE.read_text()
        assert "fill={cardFill}" in text, (
            "REQ-008: top-level node rect must use the computed cardFill var"
        )
        assert "var(--node-fill)" in text, (
            "REQ-009 Phase 4: cardFill default must read --node-fill CSS var"
        )
        assert "var(--node-fill-selected)" in text, (
            "REQ-009 Phase 4: selected-state must read --node-fill-selected CSS var"
        )
        css = INDEX_CSS.read_text()
        assert "--node-fill: #ffffff" in css, (
            "REQ-009 Phase 4: :root --node-fill must be white (#ffffff)"
        )
        assert "--node-fill-selected: #f1f5f9" in css, (
            "REQ-009 Phase 4: :root --node-fill-selected must be slate-100 (#f1f5f9)"
        )

    def test_child_node_background_uses_type_tint_or_brand(self):
        """REQ-008: ChildNode uses the same resolution
        (childFill = brand-solid OR TYPE_TINTS[type] OR white). Assert the
        computed-var path is wired, not a static white fill."""
        text = TOPOLOGY_NODE.read_text()
        assert "fill={childFill}" in text, (
            "REQ-008: child rect must use the computed childFill var"
        )

    def test_no_dark_node_backgrounds_remain(self):
        text = TOPOLOGY_NODE.read_text()
        for hex_color in ("#0f172a", "#111827", "#1e293b"):
            # `#1e293b` was the selected-state dark color; should be gone too.
            assert hex_color not in text, (
                f"REQ-006 regression: dark node fill {hex_color!r} reappeared in TopologyNode.jsx"
            )

    def test_node_label_text_is_dark_slate(self):
        """REQ-006 + REQ-008 + REQ-009 Phase 4: label color resolved via
        `labelColor` (white on brand-solid, var(--node-text) otherwise).
        The dark-slate hex now lives in index.css :root, not TopologyNode."""
        text = TOPOLOGY_NODE.read_text()
        assert "fill={labelColor}" in text, (
            "REQ-008: node label must use computed labelColor"
        )
        # Post-Phase 4: labelColor reads from CSS var, not hex literal.
        assert "var(--node-text)" in text, (
            "REQ-009 Phase 4: labelColor must read from --node-text CSS var"
        )
        # The dark-slate hex (#1f2937) lives in index.css :root --node-text now.
        css = INDEX_CSS.read_text()
        assert "--node-text: #1f2937" in css, (
            "REQ-009 Phase 4: --node-text in :root must be #1f2937 (dark slate)"
        )
        assert "'#e5e7eb'" not in text, (
            "REQ-006 regression: dark-mode label color #e5e7eb reappeared"
        )

    def test_status_colors_aligned_with_topology_map(self):
        """Post-Phase 4: TopologyNode's runtime STATUS_COLORS table reads
        var(--status-*) and the hex equivalents are kept in
        STATUS_COLORS_HEX_REFERENCE as the cross-file invariant anchor.
        Both still need to exist so the dual-table consistency test below
        keeps working."""
        node_text = TOPOLOGY_NODE.read_text()
        # The hex equivalents still appear (in STATUS_COLORS_HEX_REFERENCE).
        for hex_color in ("'#16a34a'", "'#ca8a04'", "'#dc2626'", "'#94a3b8'"):
            assert hex_color in node_text, (
                f"REQ-009 Phase 4: TopologyNode STATUS_COLORS_HEX_REFERENCE "
                f"missing {hex_color} — needed for the cross-file invariant test"
            )
        # Old neon shouldn't leak back in.
        for hex_color in ("'#22c55e'", "'#eab308'", "'#ef4444'"):
            assert hex_color not in node_text, (
                f"REQ-006 regression: dark-mode neon {hex_color} reappeared in TopologyNode.jsx"
            )
        # The runtime table must use CSS vars now.
        assert "var(--status-healthy)" in node_text, (
            "REQ-009 Phase 4: runtime STATUS_COLORS must read CSS vars"
        )


class TestTopologyMapBoundaryLabels:
    """REQ-006: drawBox boundary labels are full-opacity (the partial-frame
    `frameOpacity` only fades the wrapper stroke). Env boundary stroke
    aligned to CV_ACCENT."""

    def test_drawbox_label_opacity_is_one(self):
        text = TOPOLOGY_MAP.read_text()
        # The label <text> inside drawBox must use opacity={1}, not the
        # legacy `opacity + 0.2` math that left labels faint on light bg.
        assert "fontWeight={700} opacity={1}>{label}" in text, (
            "REQ-006: boundary label opacity must be 1 so titles read on cream bg"
        )

    def test_drawbox_signature_uses_frameopacity(self):
        text = TOPOLOGY_MAP.read_text()
        # Renamed from `opacity` to `frameOpacity` — the function only
        # applies it to the wrapper stroke, not the text labels.
        assert "const drawBox = (x, y, w, h, color, dash, frameOpacity" in text, (
            "REQ-006: drawBox param renamed to frameOpacity so the partial "
            "application is explicit in the signature"
        )

    def test_l1_l2_l3_boundary_labels_are_neutral_gray(self):
        """User feedback 2026-05-24: hierarchical boundary labels (company /
        solution / environment) are STRUCTURAL, not status — color should
        be reserved for meaning (green=healthy, yellow/red=problems). All
        three levels use --canvas-boundary-label, a deliberately quiet slate
        (slate-400 light / slate-300 dark) so they read but don't compete
        with the real status signal. Dashed-line cadence (4 3 / 6 4 / 8 4)
        is what differentiates the three nesting levels visually."""
        text = TOPOLOGY_MAP.read_text()
        # All three drawBox call sites pass canvas-boundary-label as the color.
        for marker in (
            "envBounds.map((eb, i) => drawBox(",
            "Object.entries(solutions).map(([name, sol], i) => drawBox(",
            "drawBox(\n                coMinX - pad.co",
        ):
            assert marker in text or marker.replace("\n                ", "") in text, (
                f"REQ-009 boundary-label test could not locate call site for {marker!r}"
            )
        # The three drawBox calls collectively contain
        # 'var(--canvas-boundary-label)' three times (env, solution, company).
        count = text.count("'var(--canvas-boundary-label)'")
        assert count >= 3, (
            f"REQ-009: expected at least 3 'var(--canvas-boundary-label)' uses "
            f"(env+solution+company drawBox calls); found {count}. Reverting "
            f"any of those to a colored accent collapses the "
            f"color-equals-meaning principle the user established 2026-05-24."
        )
        # The var itself must be defined in both themes.
        css = INDEX_CSS.read_text()
        assert "--canvas-boundary-label: #94a3b8" in css, (
            "REQ-009 user feedback 2026-05-24: :root --canvas-boundary-label "
            "must be slate-400 (#94a3b8) — readable on cream but quiet"
        )
        assert "--canvas-boundary-label: #cbd5e1" in css, (
            "REQ-009 user feedback 2026-05-24: .dark --canvas-boundary-label "
            "must be slate-300 (#cbd5e1) — readable on purple-950 but quiet"
        )
        # Make sure the previously-colored vars aren't re-introduced as
        # boundary fills (they're still valid CSS vars but shouldn't be
        # used HERE).
        # Slice the L1/L2/L3 region of the file and assert old accent vars
        # don't appear inside it.
        l3_idx = text.index("envBounds.map((eb, i) => drawBox(")
        # Walk forward until end of L1 drawBox.
        l1_end = text.index(")}", text.index("All Projects`, formatCost(totalCost), 12"))
        boundary_block = text[l3_idx:l1_end]
        for forbidden in (
            "'var(--canvas-accent-primary)'",
            "'var(--canvas-accent-solution)'",
            "'var(--canvas-accent-company)'",
        ):
            assert forbidden not in boundary_block, (
                f"REQ-009 user feedback: {forbidden} reappeared in the L1/L2/L3 "
                f"boundary block — those labels must stay neutral gray (color is "
                f"reserved for status/identity, not hierarchy)"
            )

    def test_legacy_cyan_gone_from_topology_map(self):
        text = TOPOLOGY_MAP.read_text()
        # The old ColdVault accent shouldn't appear anywhere in the file
        # any more — it was the only place that hex was used.
        assert "#5BD3F4" not in text, (
            "REQ-006 regression: legacy CV cyan #5BD3F4 leaked back into TopologyMap"
        )


class TestStatusColorsCrossFileConsistency:
    """REQ-006: the STATUS_COLORS table is duplicated in TopologyMap and
    TopologyNode. They MUST stay in lockstep so border colors / status dots
    on nodes always match the matching status indicators on group strokes.
    Tests the actual cross-file invariant instead of hardcoded literals."""

    @staticmethod
    def _parse_status_colors(text: str) -> dict:
        """Extract the STATUS_COLORS hex table (keys → hex values).

        TopologyMap.jsx still uses raw hex (STATUS_COLORS block); since
        REQ-009 Phase 4 TopologyNode's runtime STATUS_COLORS reads CSS
        vars, so we look at STATUS_COLORS_HEX_REFERENCE there — kept
        specifically as the cross-file invariant anchor. Try both block
        names so the parser works against either file.
        """
        import re
        # Prefer the dedicated hex-reference block if present (TopologyNode),
        # else fall back to STATUS_COLORS (TopologyMap and older code).
        block_match = re.search(
            r"const STATUS_COLORS_HEX_REFERENCE = \{(.+?)\}", text, re.DOTALL
        ) or re.search(
            r"const STATUS_COLORS = \{(.+?)\}", text, re.DOTALL
        )
        assert block_match, "Neither STATUS_COLORS_HEX_REFERENCE nor STATUS_COLORS block found"
        block = block_match.group(1)
        # Match e.g. `healthy: '#16a34a'` or `'not monitored': '#94a3b8'`
        entries = re.findall(
            r"['\"]?([A-Za-z][\w ]*)['\"]?\s*:\s*['\"](#[0-9a-fA-F]{6})['\"]",
            block,
        )
        return dict(entries)

    def test_topology_map_keys_are_subset_of_topology_node(self):
        """9r round-2 tightening: TopologyMap is the canonical STATUS_COLORS
        table. TopologyNode extends it with child-only keys (disabled,
        dynamic, 'not monitored'). Every key TopologyMap defines MUST exist
        in TopologyNode — otherwise a group status TopologyMap can produce
        would have no matching node-side render path and silently fall
        through to 'unknown'."""
        node_colors = self._parse_status_colors(TOPOLOGY_NODE.read_text())
        map_colors = self._parse_status_colors(TOPOLOGY_MAP.read_text())
        missing = set(map_colors) - set(node_colors)
        assert not missing, (
            f"REQ-006: TopologyNode STATUS_COLORS is missing keys {missing} "
            f"that TopologyMap defines. The two tables must stay in lockstep "
            f"(TopologyMap canonical, TopologyNode may be a superset)."
        )

    def test_shared_keys_have_identical_hexes(self):
        node_colors = self._parse_status_colors(TOPOLOGY_NODE.read_text())
        map_colors = self._parse_status_colors(TOPOLOGY_MAP.read_text())
        shared = set(node_colors) & set(map_colors)
        # Sanity: there must be overlap; the tables are meant to align.
        assert len(shared) >= 5, (
            f"Expected overlap between STATUS_COLORS tables; got {shared}"
        )
        for key in shared:
            assert node_colors[key] == map_colors[key], (
                f"REQ-006: STATUS_COLORS[{key!r}] drift — "
                f"TopologyNode={node_colors[key]!r} vs "
                f"TopologyMap={map_colors[key]!r}. Keep the tables in lockstep."
            )


class TestTypeBasedIdentity:
    """REQ-008: type-based fill tints + quiet healthy borders + brand-solid
    primary nodes. Structural guards so the slide-resembling identity does
    not silently regress to the previous status-dominant palette."""

    def test_quiet_healthy_stroke_constant_exists(self):
        text = TOPOLOGY_NODE.read_text()
        # Post-Phase 4: QUIET_HEALTHY_STROKE reads a CSS var; the hex lives
        # in :root --node-stroke-quiet so dark mode can substitute.
        assert "const QUIET_HEALTHY_STROKE = 'var(--node-stroke-quiet)'" in text, (
            "REQ-008(A)/Phase 4: healthy nodes must use --node-stroke-quiet var"
        )
        css = INDEX_CSS.read_text()
        assert "--node-stroke-quiet: #cbd5e1" in css, (
            "REQ-008(A): :root --node-stroke-quiet must be slate-300 (#cbd5e1)"
        )
        assert "HEALTHY_STATUSES = new Set(['healthy', 'deployed'])" in text, (
            "REQ-008(A): healthy + deployed share the quiet-border treatment"
        )

    def test_type_tints_map_has_expected_categories(self):
        """Post-Phase 4: TYPE_TINTS keys map to CSS vars; the actual hex
        colors live in index.css :root + .dark blocks so dark mode can
        substitute translucent washes over the purple-800 surface."""
        text = TOPOLOGY_NODE.read_text()
        assert "const TYPE_TINTS = {" in text, (
            "REQ-008(B): TYPE_TINTS map must be declared"
        )
        # Runtime entries read CSS vars.
        assert "provider: 'var(--tint-provider)'" in text
        for key, var in (
            ("load_balancer", "--tint-lb"),
            ("cdn", "--tint-cdn"),
            ("ingress", "--tint-ingress"),
            ("mig", "--tint-mig"),
            ("container", "--tint-container"),
            ("vm", "--tint-vm"),
            ("cloud_run", "--tint-cloud-run"),
        ):
            assert f"{key}: 'var({var})'" in text, (
                f"REQ-009 Phase 4: TYPE_TINTS[{key!r}] must read var({var})"
            )
        # The hex values live in :root in index.css.
        css = INDEX_CSS.read_text()
        assert "--tint-provider: #f0fdf4" in css, (
            "REQ-008(B): :root --tint-provider must be green-50 (#f0fdf4)"
        )
        assert "--tint-lb: #f0fdfa" in css, (
            "REQ-008(B): :root --tint-lb must be teal-50 (#f0fdfa)"
        )
        assert "--tint-mig: #eff6ff" in css, (
            "REQ-008(B): :root --tint-mig must be blue-50 (#eff6ff)"
        )

    def test_brand_primary_solid_blue_path_exists(self):
        """Post-Phase 4: brand-primary palette reads CSS vars; hexes live
        in index.css :root (royal blue light) and .dark (ColdVault medium
        blue) so the brand-solid cards flip across themes."""
        text = TOPOLOGY_NODE.read_text()
        assert "function isBrandPrimary(node)" in text, (
            "REQ-008(C): isBrandPrimary helper must exist"
        )
        assert "node.brand === 'primary'" in text, (
            "REQ-008(C): brand=primary manifest field must still opt-in any node"
        )
        assert "node.type === 'application'" in text, (
            "REQ-008(C): type=application default must still qualify for solid blue"
        )
        # Solid blue palette via CSS vars now.
        assert "const BRAND_PRIMARY_FILL = 'var(--brand-primary-fill)'" in text, (
            "REQ-009 Phase 4: BRAND_PRIMARY_FILL must read --brand-primary-fill var"
        )
        assert "const BRAND_PRIMARY_TEXT = 'var(--brand-primary-text)'" in text, (
            "REQ-009 Phase 4: BRAND_PRIMARY_TEXT must read --brand-primary-text var"
        )
        # The actual hexes live in index.css.
        css = INDEX_CSS.read_text()
        assert "--brand-primary-fill: #2563eb" in css, (
            "REQ-009 Phase 4: :root --brand-primary-fill must be royal blue (#2563eb)"
        )
        # Resolution path branches on brandSolid → BRAND_PRIMARY_FILL.
        assert "brandSolid" in text and "BRAND_PRIMARY_FILL" in text, (
            "REQ-008(C): cardFill resolution must branch on brandSolid → BRAND_PRIMARY_FILL"
        )

    def test_topology_map_group_stroke_quiets_on_healthy(self):
        text = TOPOLOGY_MAP.read_text()
        # The healthy-group stroke uses the same --node-stroke-quiet var as
        # TopologyNode after REQ-009 Phase 4b.
        assert "g._health === 'healthy' || g._health === 'deployed'" in text, (
            "REQ-008: group stroke must quiet on healthy/deployed too — "
            "matches the per-node treatment so the whole canvas stops painting green"
        )
        assert "var(--node-stroke-quiet)" in text, (
            "REQ-009 Phase 4b: TopologyMap healthy group stroke must read "
            "--node-stroke-quiet (same var TopologyNode uses)"
        )


class TestBrandSolidSelectionAndGlow:
    """REQ-008 9r round-1 fixes — brand-solid + selected must produce a
    distinct fill (the original implementation collapsed both states to
    one color), and healthy nodes must not emit a green drop-shadow
    (which would re-introduce the green wash REQ-008 set out to fix)."""

    def test_brand_solid_selected_uses_lighter_blue(self):
        """Post-Phase 4: brand-solid + selected reads BRAND_PRIMARY_FILL_SELECTED
        (var --brand-primary-fill-selected). The hex #3b82f6 lives in :root.
        Round-7 retightened: pin the EXACT ternary structure so a regression
        that swaps selected/unselected (or drops the SELECTED branch)
        fails loudly, not silently."""
        text = TOPOLOGY_NODE.read_text()
        # Runtime: constant references the CSS var.
        assert "const BRAND_PRIMARY_FILL_SELECTED = 'var(--brand-primary-fill-selected)'" in text, (
            "REQ-009 Phase 4: BRAND_PRIMARY_FILL_SELECTED must read its CSS var"
        )
        # Tight ternary: brand-solid AND selected → LIGHTER. Tolerates one
        # newline+indent between `brandSolid` and `?` (Prettier-stable shape).
        import re
        pattern = re.compile(
            r"brandSolid\s*\?\s*\(\s*selected\s*\?\s*BRAND_PRIMARY_FILL_SELECTED\s*:\s*BRAND_PRIMARY_FILL\s*\)",
            re.DOTALL,
        )
        assert pattern.search(text), (
            "REQ-008 round-7 retightening: cardFill must literally compute "
            "`brandSolid ? (selected ? BRAND_PRIMARY_FILL_SELECTED : BRAND_PRIMARY_FILL) : ...`. "
            "A regression that swaps the inner branches (or drops SELECTED) "
            "would silently break selection visibility."
        )
        # The hex itself lives in index.css :root.
        css = INDEX_CSS.read_text()
        assert "--brand-primary-fill-selected: #3b82f6" in css, (
            "REQ-008 + Phase 4: :root --brand-primary-fill-selected must be blue-500"
        )

    def test_healthy_does_not_emit_green_glow(self):
        text = TOPOLOGY_NODE.read_text()
        # GLOW_FILTER should no longer map healthy → green glow.
        assert "healthy: 'url(#glow-green)'" not in text, (
            "REQ-008: healthy nodes must not emit a green drop-shadow — would "
            "undo REQ-008(A) at the SVG-filter layer"
        )
        # But the degraded/error glows still exist as alert overlays.
        assert "degraded: 'url(#glow-yellow)'" in text
        assert "error: 'url(#glow-red)'" in text


class TestBrandPrimaryLeafOnly:
    """REQ-008 9r round-2 fix — isBrandPrimary applies the type=application
    default only to LEAF nodes so nested-children subtrees aren't painted
    solid blue. Manifest-flagged `brand: primary` keeps the leaf check
    skipped (explicit author opt-in)."""

    def test_helper_enforces_leaf_only_for_application_default(self):
        text = TOPOLOGY_NODE.read_text()
        # The body of isBrandPrimary uses Array.isArray(node.children) and
        # gates the type=application default on `!hasChildren`.
        assert "Array.isArray(node.children) && node.children.length > 0" in text, (
            "REQ-008: isBrandPrimary must compute hasChildren via Array.isArray"
        )
        assert "node.type === 'application' && !hasChildren" in text, (
            "REQ-008: type=application qualifies for brand-solid only when leaf"
        )
        # Explicit brand override still wins regardless of children.
        assert "node.brand === 'primary'" in text, (
            "REQ-008: explicit brand=primary manifest field must still opt-in any node"
        )

    def test_dead_green_glow_filter_removed(self):
        """9r round-2 cleanup — the <filter id=\"glow-green\"> element was
        unreferenced after dropping healthy from GLOW_FILTER. Removing it
        avoids dead DOM and prevents a future regression that re-wires
        healthy → green by accident."""
        text = TOPOLOGY_NODE.read_text()
        assert 'id="glow-green"' not in text, (
            "REQ-008: dead <filter id=\"glow-green\"> must be removed from <defs>"
        )


class TestGlowFiltersDeclaredOnceAtRoot:
    """REQ-011: shared SVG <filter> elements live in TopologyMap's root <defs>,
    not in per-node TopologyNode <defs>. Duplicate IDs in an SVG document are
    undefined behaviour per the spec; the ~50-node topology previously
    injected ~100 duplicate <filter id="glow-…"> elements with inconsistent
    cross-browser rendering."""

    def test_topology_map_root_defs_declares_glow_yellow_once(self):
        text = TOPOLOGY_MAP.read_text()
        assert text.count('<filter id="glow-yellow">') == 1, (
            "REQ-011: TopologyMap root <defs> must declare <filter id=\"glow-yellow\"> "
            "exactly once (currently {} occurrence(s))"
        ).format(text.count('<filter id="glow-yellow">'))

    def test_topology_map_root_defs_declares_glow_red_once(self):
        text = TOPOLOGY_MAP.read_text()
        assert text.count('<filter id="glow-red">') == 1, (
            "REQ-011: TopologyMap root <defs> must declare <filter id=\"glow-red\"> "
            "exactly once (currently {} occurrence(s))"
        ).format(text.count('<filter id="glow-red">'))

    def test_topology_node_emits_no_filter_elements(self):
        """Per-node <filter id=\"…\"> declarations are the bug — the ID collides
        with every other rendered instance of the same node component."""
        text = TOPOLOGY_NODE.read_text()
        assert '<filter id=' not in text, (
            "REQ-011: TopologyNode must not declare any <filter id=\"…\"> elements; "
            "they belong in TopologyMap's root <defs>"
        )

    def test_topology_node_emits_no_defs_block(self):
        """With glow filters hoisted out, TopologyNode has nothing left to put
        in a <defs> — the whole block should be gone, not just emptied."""
        text = TOPOLOGY_NODE.read_text()
        assert "<defs>" not in text, (
            "REQ-011: TopologyNode should have no <defs> block at all after the "
            "filters were hoisted to TopologyMap"
        )

    def test_glow_filter_url_references_still_intact(self):
        """The GLOW_FILTER map must still reference both filter URLs — the
        references resolve up the SVG scope to TopologyMap's defs at render
        time, so renaming or dropping them would silently break alert glows."""
        text = TOPOLOGY_NODE.read_text()
        assert "url(#glow-yellow)" in text, (
            "REQ-011: GLOW_FILTER must still reference url(#glow-yellow) — the "
            "filter ID is declared in TopologyMap's root <defs>"
        )
        assert "url(#glow-red)" in text, (
            "REQ-011: GLOW_FILTER must still reference url(#glow-red)"
        )

    def test_glow_filter_floodcolor_reads_css_vars(self):
        """REQ-012: glow filter floodColor must read CSS vars (not hex literals)
        so dark mode can substitute brighter hues that read against the
        purple-950 canvas. The same REQ-009 Phase 4 pattern the rest of the
        SVG palette uses."""
        text = TOPOLOGY_MAP.read_text()
        assert 'floodColor="var(--glow-degraded)"' in text, (
            "REQ-012: glow-yellow floodColor must be var(--glow-degraded), "
            "not a hex literal"
        )
        assert 'floodColor="var(--glow-error)"' in text, (
            "REQ-012: glow-red floodColor must be var(--glow-error), "
            "not a hex literal"
        )
        # Make sure the old hex literals didn't survive in either filter line.
        for hex_literal in ('#ca8a04', '#dc2626'):
            for filter_line in [
                line for line in text.splitlines()
                if '<filter id="glow-' in line
            ]:
                assert hex_literal not in filter_line, (
                    f"REQ-012: hex literal {hex_literal} must not appear in "
                    f"a <filter id=\"glow-…\"> line — use the CSS var instead"
                )

    # (TestGlowFiltersDeclaredOnceAtRoot continues below)
    def test_glow_css_vars_declared_in_both_themes(self):
        """REQ-012: --glow-degraded and --glow-error must be declared in BOTH
        the :root and the .dark blocks of index.css. Without the .dark-block
        substitution, the dark theme just gets the same dim light-mode hex,
        which is the bug we're solving.

        9r round-1 finding (advisory): a simple count>=2 check could pass on
        a file that declares both vars twice in :root and zero times in
        .dark — false-clean. This test extracts each block by string and
        asserts the var name appears inside each block specifically."""
        text = INDEX_CSS.read_text()

        def block_body(opener):
            """Return the body of a CSS block opened by `opener` (e.g. ':root {'
            or '.dark {'). Naive matching by balanced braces is enough here
            because index.css uses one-level-deep declaration blocks."""
            start = text.find(opener)
            assert start >= 0, f"REQ-012: expected '{opener}' block in index.css"
            depth = 0
            body_start = text.find('{', start) + 1
            i = body_start
            while i < len(text):
                if text[i] == '{':
                    depth += 1
                elif text[i] == '}':
                    if depth == 0:
                        return text[body_start:i]
                    depth -= 1
                i += 1
            raise AssertionError(f"REQ-012: '{opener}' block never closed")

        root_block = block_body(':root {')
        dark_block = block_body('.dark {')

        for var_name in ('--glow-degraded:', '--glow-error:'):
            assert var_name in root_block, (
                f"REQ-012: {var_name} must be declared in the :root block"
            )
            assert var_name in dark_block, (
                f"REQ-012: {var_name} must be declared in the .dark block — "
                "without it the dark theme inherits the light-mode hex"
            )


# ====================================================================
# REQ-009 + REQ-010 — Phase 1 infrastructure guards
# ====================================================================

INDEX_HTML = REPO / "frontend" / "index.html"
USE_THEME = REPO / "frontend" / "src" / "hooks" / "useTheme.jsx"
MAIN_JSX = REPO / "frontend" / "src" / "main.jsx"
STATUS_HEADER = REPO / "frontend" / "src" / "components" / "StatusHeader.jsx"


class TestTailwindDarkModeAndColdVaultPalette:
    """REQ-009: darkMode:'class'. REQ-010: ColdVault palette + Lato."""

    def test_dark_mode_is_class_based(self):
        text = TAILWIND_CONFIG.read_text()
        assert "darkMode: 'class'" in text, (
            "REQ-009: Tailwind darkMode must be 'class' (not 'media') so the "
            "toggle controls the theme, not OS prefers-color-scheme"
        )

    def test_purple_scale_has_coldvault_anchors(self):
        text = TAILWIND_CONFIG.read_text()
        # The three brand anchors that link GlassHood to ColdVault visually.
        assert "500: '#1E4970'" in text, "purple-500 must be ColdVault dark anchor"
        assert "300: '#5BD3F4'" in text, "purple-300 must be ColdVault medium blue"
        assert "100: '#AEEDF5'" in text, "purple-100 must be ColdVault light blue"
        # Sample the dark end so the dark-mode backdrop is wired.
        assert "950: '#020810'" in text, "purple-950 must be near-black-blue backdrop"

    def test_accent_scale_has_brand_blue(self):
        text = TAILWIND_CONFIG.read_text()
        assert "500: '#5BD3F4'" in text, "accent-500 must be ColdVault medium blue"
        assert "300: '#AEEDF5'" in text, "accent-300 must be ColdVault light blue"

    def test_lato_is_primary_sans_font(self):
        text = TAILWIND_CONFIG.read_text()
        assert "fontFamily" in text
        assert "'Lato'" in text, "Lato must be in fontFamily.sans (matches ColdVault)"


class TestIndexCssThemeBlocks:
    """REQ-009: :root + .dark CSS-var blocks for the SVG canvas palette.
    REQ-010: Lato @import; ColdVault purple-950 dark backdrop."""

    def test_lato_imported(self):
        text = INDEX_CSS.read_text()
        assert "fonts.googleapis.com/css2?family=Lato" in text, (
            "REQ-010: Lato must be imported via Google Fonts in index.css"
        )

    def test_root_css_var_block_exists(self):
        text = INDEX_CSS.read_text()
        # Sample tokens from the canvas + node + brand groups.
        for var in ('--canvas-bg', '--node-fill', '--node-text', '--brand-primary-fill'):
            assert var in text, f"REQ-009: CSS variable {var} must be declared"

    def test_dark_block_overrides_canvas_to_purple_950(self):
        text = INDEX_CSS.read_text()
        assert ".dark {" in text, "REQ-009: .dark CSS-var block must exist"
        # The dark canvas-bg flips to ColdVault purple-950 (#020810).
        # Slice the .dark block and check.
        dark_idx = text.index(".dark {")
        dark_block = text[dark_idx:dark_idx + 2000]
        assert "--canvas-bg: #020810" in dark_block, (
            "REQ-009/010: dark canvas-bg must be ColdVault purple-950 (#020810)"
        )

    def test_dark_body_background_is_purple_950(self):
        text = INDEX_CSS.read_text()
        assert ".dark body" in text, "REQ-009: .dark body selector must exist"
        # Flat purple-950 (niobe's ops-dashboard recommendation, not the gradient).
        body_idx = text.index(".dark body")
        body_block = text[body_idx:body_idx + 200]
        assert "#020810" in body_block, (
            "REQ-009/010: .dark body must use flat purple-950 (#020810) backdrop"
        )

    def test_prefers_reduced_motion_opt_out(self):
        text = INDEX_CSS.read_text()
        assert "prefers-reduced-motion" in text, (
            "REQ-009: cross-fade must respect prefers-reduced-motion for a11y"
        )


class TestFoucScript:
    """REQ-009: FOUC-prevention inline script runs BEFORE React mounts."""

    def test_fouc_script_present_in_head(self):
        text = INDEX_HTML.read_text()
        assert "glasshood-theme-preference" in text, (
            "REQ-009: FOUC script must read the glasshood-theme-preference "
            "localStorage key"
        )
        assert "prefers-color-scheme: dark" in text, (
            "REQ-009: FOUC script must consult OS prefers-color-scheme for auto"
        )
        assert "classList.add" in text, (
            "REQ-009: FOUC script must set 'dark' or 'light' class on <html>"
        )

    def test_fouc_script_precedes_react_bundle(self):
        text = INDEX_HTML.read_text()
        fouc_idx = text.index("glasshood-theme-preference")
        react_idx = text.index("/src/main.jsx")
        assert fouc_idx < react_idx, (
            "REQ-009: FOUC script must run BEFORE the React bundle loads, "
            "otherwise the first paint will flash the wrong theme"
        )


class TestUseThemeHook:
    """REQ-009: React Context + two-piece state (themePreference + theme)."""

    def test_use_theme_file_exists(self):
        assert USE_THEME.exists(), (
            "REQ-009: frontend/src/hooks/useTheme.jsx must exist"
        )

    def test_two_piece_state(self):
        text = USE_THEME.read_text()
        # Two pieces of state per niobe's reference §1.
        assert "themePreference" in text, (
            "REQ-009: must expose themePreference state ('auto'|'dark'|'light')"
        )
        assert "setTheme" in text or "useState" in text, (
            "REQ-009: must have a concrete theme state derived from preference"
        )

    def test_localstorage_key_is_glasshood_theme_preference(self):
        text = USE_THEME.read_text()
        assert "'glasshood-theme-preference'" in text or '"glasshood-theme-preference"' in text, (
            "REQ-009: localStorage key must be 'glasshood-theme-preference' "
            "(matches the FOUC script)"
        )

    def test_match_media_subscription_for_auto(self):
        text = USE_THEME.read_text()
        assert "matchMedia" in text, (
            "REQ-009: must subscribe to matchMedia for OS prefers-color-scheme "
            "while in 'auto' mode"
        )
        assert "prefers-color-scheme" in text

    def test_html_class_toggled(self):
        text = USE_THEME.read_text()
        assert "documentElement" in text and "classList" in text, (
            "REQ-009: hook must toggle .dark / .light on <html> so Tailwind "
            "dark: variants resolve and CSS-var blocks switch"
        )


class TestThemeProviderWired:
    """REQ-009: <ThemeProvider> wraps <App> in main.jsx."""

    def test_main_wires_theme_provider(self):
        text = MAIN_JSX.read_text()
        assert "ThemeProvider" in text, (
            "REQ-009: main.jsx must wrap <App> in <ThemeProvider>"
        )
        assert "useTheme" in text or "./hooks/useTheme" in text, (
            "REQ-009: main.jsx must import from the useTheme module"
        )


class TestStatusHeaderToggle:
    """REQ-009: 3-button segmented theme toggle in StatusHeader."""

    def test_toggle_uses_three_lucide_icons(self):
        text = STATUS_HEADER.read_text()
        # Monitor for Auto, Sun for Light, Moon for Dark.
        assert "Monitor" in text, "REQ-009: StatusHeader toggle must include Monitor (Auto)"
        assert "Sun" in text, "REQ-009: StatusHeader toggle must include Sun (Light)"
        assert "Moon" in text, "REQ-009: StatusHeader toggle must include Moon (Dark)"

    def test_toggle_calls_use_theme(self):
        text = STATUS_HEADER.read_text()
        assert "useTheme" in text, (
            "REQ-009: StatusHeader must call useTheme() to drive the toggle"
        )

    def test_three_radio_options(self):
        text = STATUS_HEADER.read_text()
        # 3-button segmented control: auto / light / dark each rendered as radio.
        for value in ("'auto'", "'light'", "'dark'"):
            assert value in text, (
                f"REQ-009: StatusHeader toggle must expose {value} as a selectable option"
            )


class TestNodeDetailModalBannerReadable:
    """REQ-009: the manifest-not-monitored banner (the one user flagged 2026-05-23)
    must have BOTH a light and a dark variant — no more dark-on-dark unreadable."""

    def test_banner_has_light_and_dark_bg(self):
        text = (REPO / "frontend" / "src" / "components" / "NodeDetailModal.jsx").read_text()
        # The old offender: `bg-gray-800/50 border border-gray-700 text-gray-400`
        # which only read on a dark canvas. New banner must have a light pair.
        assert "bg-gray-100 dark:bg-purple-700/50" in text, (
            "REQ-009: 'not yet connected' banner must use bg-gray-100 (light) + "
            "dark:bg-purple-700/50 so it reads on both themes"
        )

    def test_banner_text_color_pair(self):
        text = (REPO / "frontend" / "src" / "components" / "NodeDetailModal.jsx").read_text()
        assert "text-gray-700 dark:text-purple-200" in text, (
            "REQ-009: banner text must be dark-slate on light, purple-200 on dark"
        )


# ====================================================================
# REQ-009 — round 3 a11y + browser-compat guards
# ====================================================================

class TestThemeToggleA11y:
    """REQ-009 round-3 fix: ThemeToggle implements WAI-ARIA radiogroup
    arrow-key navigation (ArrowLeft/Right/Up/Down + Home/End) and roving
    tabindex so screen-reader / keyboard-only users can move between the
    three options."""

    def test_keyboard_handler_present(self):
        text = STATUS_HEADER.read_text()
        assert "onKeyDown" in text, (
            "REQ-009: ThemeToggle radiogroup must register a keyboard handler"
        )
        # Each arrow key + Home/End handled.
        for key in ("ArrowRight", "ArrowLeft", "ArrowUp", "ArrowDown", "Home", "End"):
            assert key in text, (
                f"REQ-009 a11y: ThemeToggle keyboard handler must respond to '{key}'"
            )

    def test_roving_tabindex(self):
        text = STATUS_HEADER.read_text()
        # tabIndex={active ? 0 : -1} — only the selected option is in the
        # tab sequence; arrow keys move within the group.
        assert "tabIndex={active ? 0 : -1}" in text, (
            "REQ-009 a11y: ThemeToggle must use roving tabindex (only the "
            "active radio is in the document tab order)"
        )


class TestUseThemeBrowserCompat:
    """REQ-009 round-2 fix: matchMedia subscription falls back to the
    legacy addListener/removeListener API on older Safari + WebView
    that don't support addEventListener on MediaQueryList."""

    def test_addlistener_fallback_present(self):
        text = USE_THEME.read_text()
        # Both modern + legacy paths must be feature-detected.
        assert "addEventListener" in text, "REQ-009: modern listener still wired"
        assert "addListener" in text, (
            "REQ-009: legacy MediaQueryList.addListener fallback must exist for "
            "older Safari / WebViews that don't support addEventListener"
        )
        assert "removeListener" in text, (
            "REQ-009: matching removeListener cleanup required to avoid leaks"
        )


class TestThemeToggleFocusFollowsSelection:
    """REQ-009 round-4 fix: WAI-ARIA radiogroup requires that DOM focus
    moves with selection (otherwise the visible focus ring stays on the
    previous button while aria-checked moves, and SRs announce the wrong
    option as focused)."""

    def test_buttons_carry_refs(self):
        text = STATUS_HEADER.read_text()
        assert "buttonRefs" in text, (
            "REQ-009 a11y: ThemeToggle must hold refs to its option buttons "
            "so keyboard selection can move DOM focus too"
        )
        assert "ref={el => { buttonRefs.current[idx] = el }}" in text, (
            "REQ-009 a11y: each option button must register its ref via idx"
        )

    def test_focus_called_after_selection(self):
        text = STATUS_HEADER.read_text()
        # Microtask defer so React commits the new tabIndex before .focus().
        assert ".focus()" in text, (
            "REQ-009 a11y: keyboard select() must call .focus() on the new button"
        )

    def test_click_routes_through_select(self):
        """REQ-009 round-7 fix: onClick uses select(idx), not setThemePreference
        directly, so clicks move DOM focus same as arrow keys. Without this
        a click+then-arrow combo fires arrows against the wrong focused
        element until the browser reconciles."""
        text = STATUS_HEADER.read_text()
        assert "onClick={() => select(idx)}" in text, (
            "REQ-009 a11y round-7: ThemeToggle button onClick must route "
            "through select(idx) (which calls .focus()) instead of "
            "setThemePreference directly — otherwise click leaves focus "
            "on the previously-active radio"
        )


class TestThemeToggleAutoRepeatAndCompat:
    """REQ-009 round-5 fixes — queueMicrotask fallback for legacy Safari,
    and a ref-tracker so arrow-key auto-repeat doesn't fire against a
    stale `currentIdx` closure."""

    def test_defer_focus_has_settimeout_fallback(self):
        text = STATUS_HEADER.read_text()
        assert "queueMicrotask" in text, (
            "REQ-009: modern path still uses queueMicrotask"
        )
        assert "setTimeout(cb, 0)" in text, (
            "REQ-009 round-5: deferFocus must fall back to setTimeout(0) "
            "on browsers that lack queueMicrotask (same legacy Safari "
            "tier the addListener fallback targets)"
        )

    def test_pref_ref_tracks_latest_preference(self):
        text = STATUS_HEADER.read_text()
        assert "prefRef" in text, (
            "REQ-009 round-5: keyboard handler must read latest preference "
            "via a ref so auto-repeat doesn't see stale closure state"
        )
        # The effect that keeps prefRef in sync with themePreference.
        assert "prefRef.current = themePreference" in text, (
            "REQ-009 round-5: useEffect must sync prefRef.current on every "
            "themePreference change"
        )


# ====================================================================
# REQ-013 — Tailwind named tokens require paired dark: variant
# ====================================================================

COMPONENTS_DIR = REPO / "frontend" / "src" / "components"
# Named-token detectors split by kind so the pairing requirement is precise:
# a line that uses `bg-surface` needs a `dark:bg-…` somewhere; a line that
# uses `border-border` needs a `dark:border-…`. A line with only `dark:text-…`
# doesn't satisfy either — that's the bug the rule catches.
# Negative-lookahead `(?![-\w])` rejects hyphenated continuations like
# `bg-surface-elevated` (a different — and currently undefined — token in
# AnomalyBadge.jsx). A bare `\b` matches at the hyphen position and would
# false-flag that token.
NAMED_BG_RE = re.compile(r'\bbg-(?:surface|card)(?![-\w])')
NAMED_BORDER_RE = re.compile(r'\bborder-border(?![-\w])')
# Allow intermediate variants (`hover:`, `focus:`, `group-hover:`, etc.)
# between `dark:` and the actual utility — the Tailwind variant order is
# `dark:hover:bg-purple-700/30` so the regex must skip those.
DARK_BG_RE = re.compile(r'\bdark:(?:[a-z-]+:)*bg-')
DARK_BORDER_RE = re.compile(r'\bdark:(?:[a-z-]+:)*border-')


class TestNoUnpairedTailwindNamedTokens:
    """REQ-013: every consumer of a named Tailwind token (`surface`, `card`,
    `border` — declared in tailwind.config.js theme.extend.colors) MUST pair
    it with a `dark:` variant on the same className. Without that pairing
    the token renders the light-mode hex unconditionally — even in dark
    mode — because Tailwind named tokens are single fixed hex values, not
    CSS variables.

    This is the regression class the REQ-009 dark-canvas hotfix (PR #75)
    caught five instances of. The test prevents the next one from shipping
    silently — the bug is invisible in light mode, only surfaces when the
    user toggles dark."""

    def _collect_violations(self):
        """Walk every .jsx file under frontend/src/components/ and return a
        list of (file_relative_path, line_number, line_text, kind) for each
        line that uses a named token without a paired dark: variant of the
        same kind. Skips lines that are pure comments.

        Pairing is checked PER KIND: a line that uses `bg-surface` /
        `bg-card` must have a `dark:…bg-…` on the same line; a line that
        uses `border-border` must have a `dark:…border-…`. A line with only
        a `dark:text-…` variant doesn't satisfy a `bg-` requirement —
        precisely the bug the rule prevents."""
        violations = []
        for jsx_file in sorted(COMPONENTS_DIR.glob("*.jsx")):
            for i, line in enumerate(jsx_file.read_text().splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("*"):
                    continue
                if NAMED_BG_RE.search(line) and not DARK_BG_RE.search(line):
                    violations.append((jsx_file.name, i, stripped, "bg"))
                if NAMED_BORDER_RE.search(line) and not DARK_BORDER_RE.search(line):
                    violations.append((jsx_file.name, i, stripped, "border"))
        return violations

    def test_no_unpaired_named_tokens_in_components(self):
        violations = self._collect_violations()
        if violations:
            msg_lines = [
                "REQ-013: found {} unpaired named-token violation(s).".format(len(violations)),
                "Each line below uses `bg-surface` / `bg-card` / `border-border` without a",
                "paired `dark:` variant of the same kind on the same line. Add a `dark:`",
                "variant (typically `dark:bg-purple-800`, `dark:bg-purple-900`, or",
                "`dark:border-purple-700`) to the same className. Named tokens are",
                "config-fixed hex values — they do NOT switch between themes automatically.",
                "",
            ]
            for fname, lineno, text, kind in violations:
                msg_lines.append(f"  {fname}:{lineno} [{kind}]: {text[:140]}")
            raise AssertionError("\n".join(msg_lines))

    def test_detection_pattern_matches_known_tokens(self):
        """Sanity-check the regex itself — if the pattern stops matching the
        three documented tokens, the whole test silently becomes a no-op
        when tailwind.config.js still defines them."""
        assert NAMED_BG_RE.search("className=\"bg-surface\"")
        assert NAMED_BG_RE.search("className=\"bg-card\"")
        assert NAMED_BORDER_RE.search("className=\"border-border\"")

    def test_detection_pattern_matches_typical_dark_variants(self):
        """The dark: regex must match typical pairing forms including the
        multi-modifier chain (`dark:hover:bg-…`) that the round-1 false-clean
        on ProjectTree.jsx:65 exposed."""
        for variant in (
            "dark:bg-purple-800",
            "dark:bg-purple-900/50",
            "dark:hover:bg-purple-700/30",
            "dark:focus:bg-purple-700",
        ):
            assert DARK_BG_RE.search(variant), (
                f"REQ-013: dark-bg regex must match {variant!r}"
            )
        for variant in (
            "dark:border-purple-700",
            "dark:hover:border-purple-500",
        ):
            assert DARK_BORDER_RE.search(variant), (
                f"REQ-013: dark-border regex must match {variant!r}"
            )
