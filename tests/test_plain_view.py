# File: tests/test_plain_view.py
# Purpose: REQ-GHA-021 — one boundary for a single solution, and no checks that can only warn.

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def test_outer_frames_only_with_more_than_one_solution():
    src = (ROOT / "frontend/src/components/TopologyMap.jsx").read_text()
    assert "const multiSolution = Object.keys(solutions).length > 1" in src
    assert "{multiSolution && Object.entries(solutions).map(([name, sol], i) => drawBox(" in src
    assert "{multiSolution && drawBox(\n                coMinX" in src
    # the environment boundary stays unconditional
    assert "{envBounds.map((eb, i) => drawBox(" in src


def test_no_gcs_bucket_poll_is_started():
    src = (ROOT / "src/api/server.py").read_text()
    assert "gcs_bucket" not in src


def test_every_cve_lookup_names_one_product_version():
    # NVD's cpeName lookup takes one exact CPE; a wildcard version answers 404 every scan.
    cfg = yaml.safe_load((ROOT / "config/security_scan.yaml").read_text())
    for comp in cfg["components"]:
        parts = comp["cpe"].split(":")
        assert len(parts) == 13 and parts[5] not in ("*", "-", ""), comp["cpe"]
