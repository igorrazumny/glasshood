# REQ-GHA-018 clause 13: the app's link preview must not depend on glasshood.ai,
# which moves to the static site; the app names its own domain.

import re
from pathlib import Path

_HTML = (Path(__file__).resolve().parent.parent / "frontend" / "index.html").read_text()


def _meta(attr, name):
    m = re.search(rf'<meta {attr}="{re.escape(name)}" content="([^"]+)"', _HTML)
    assert m, name
    return m.group(1)


def test_preview_points_at_app_domain():
    assert _meta("property", "og:url") == "https://app.glasshood.ai"
    assert _meta("property", "og:image") == "https://app.glasshood.ai/glasshood-logo-full.png"
    assert _meta("name", "twitter:image") == "https://app.glasshood.ai/glasshood-logo-full.png"


def test_preview_image_is_shipped_with_the_app():
    public = Path(__file__).resolve().parent.parent / "frontend" / "public"
    assert (public / "glasshood-logo-full.png").is_file()
