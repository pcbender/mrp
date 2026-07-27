from __future__ import annotations

import asyncio
from pathlib import Path

from mrp.admin import server

ROOT = Path(__file__).resolve().parents[1]
FAVICON = ROOT / "mrp" / "admin" / "static" / "favicon.ico"


def test_the_admin_favicon_ships_as_a_real_icon() -> None:
    assert FAVICON.is_file()
    # \x00\x00\x01\x00 is the ICO container header; a renamed PNG would render
    # in some browsers and silently fail in others.
    assert FAVICON.read_bytes()[:4] == b"\x00\x00\x01\x00"


def test_the_favicon_is_served_from_the_root_as_well_as_static() -> None:
    """Browsers ask for /favicon.ico themselves, and /static cannot answer it."""
    response = asyncio.run(server.favicon())

    assert Path(response.path) == FAVICON
    assert response.media_type == "image/x-icon"


def test_every_admin_page_links_the_icon() -> None:
    base = (ROOT / "mrp" / "admin" / "templates" / "_base.html").read_text(
        encoding="utf-8"
    )

    assert '<link rel="icon" href="/static/favicon.ico"' in base
