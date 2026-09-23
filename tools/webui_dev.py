"""Explicit two-port development entrypoint; production uses api:app at /ui/."""

from character_chat_local.api import create_app

app = create_app(
    allowed_origins=("http://127.0.0.1:5173", "http://localhost:5173"),
)
