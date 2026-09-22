"""Serve only the optional, locally built WebUI; no domain/API logic lives here."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request
from starlette.staticfiles import StaticFiles


def public_ui_request(request: Request) -> bool:
    """The login shell must load before a browser can provide its API token."""
    return request.method in {"GET", "HEAD"} and (
        request.url.path == "/ui" or request.url.path.startswith("/ui/")
    )


class WebUIFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers.update(
            {
                "Cache-Control": "no-cache",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": (
                    "default-src 'self'; script-src 'self'; style-src 'self'; "
                    "img-src 'self' data:; connect-src 'self'; "
                    "object-src 'none'; base-uri 'none'; "
                    "frame-ancestors 'none'; form-action 'self'"
                ),
            }
        )
        return response


def mount_webui(app: FastAPI, directory: str | Path | None = None) -> None:
    configured = directory or os.getenv("CHARACTER_CHAT_UI_DIR")
    path = Path(configured) if configured else Path(__file__).with_name("webui")
    if not (path / "index.html").is_file():
        if configured:
            raise ValueError("WebUI directory must contain a built index.html")
        # Source-only backend installs remain supported, without placeholder routes.
        return
    app.mount("/ui", WebUIFiles(directory=path, html=True), name="webui")
