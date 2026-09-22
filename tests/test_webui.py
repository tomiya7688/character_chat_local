from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from character_chat_local.api import create_app
from character_chat_local.models import CharacterCore, ChatMessage
from character_chat_local.providers import ProviderRegistry
from character_chat_local.storage import Storage


def test_ui_bootstraps_without_exposing_authenticated_api(tmp_path):
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "assets").mkdir()
    (ui / "index.html").write_text('<div id="root">UI shell</div>')
    (ui / "assets/app.js").write_text("console.log('static');")
    app = create_app(
        database_path=tmp_path / "chat.db",
        registry=ProviderRegistry([]),
        api_token="local-test-token",
        ui_directory=ui,
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.get("/ui/")
        assert response.status_code == 200
        assert "UI shell" in response.text
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert response.headers["x-content-type-options"] == "nosniff"
        assert client.get("/ui/assets/app.js").status_code == 200
        assert client.head("/ui/").status_code == 200
        for endpoint in ["/characters", "/providers", "/conversations", "/docs"]:
            assert client.get(endpoint).status_code == 401
        assert client.post("/ui/").status_code == 401
        assert client.get("/uisecret").status_code == 401
        assert client.get("/ui/%2e%2e/characters").status_code in {401, 404}
        assert client.get("/ui/", headers={"Host": "example.com"}).status_code == 400
        assert (
            client.get("/ui/", headers={"Origin": "https://example.com"}).status_code
            == 403
        )
        assert client.get(
            "/providers", headers={"Authorization": "Bearer local-test-token"}
        ).json() == {"providers": []}


def test_explicit_ui_directory_requires_build(tmp_path):
    with pytest.raises(ValueError, match="built index.html"):
        create_app(ui_directory=tmp_path)


def test_default_ui_does_not_mount_missing_assets(tmp_path, monkeypatch):
    from fastapi import FastAPI

    from character_chat_local import webui

    monkeypatch.delenv("CHARACTER_CHAT_UI_DIR", raising=False)
    monkeypatch.setattr(webui, "__file__", str(tmp_path / "webui.py"))
    app = FastAPI()
    webui.mount_webui(app)
    with TestClient(app) as client:
        assert client.get("/ui/").status_code == 404


def test_backward_history_windows_use_global_rowids(tmp_path):
    db = Storage(tmp_path / "chat.db")
    character = CharacterCore(name="Window")
    db.save_character(character)
    conversation = db.create_conversation(character.id)
    other = db.create_conversation(character.id)
    for i in range(205):
        db.add_message(conversation, ChatMessage(role="user", content=str(i)))
        db.add_message(other, ChatMessage(role="user", content="other"))
    latest = db.list_message_records(conversation, tail=True)
    assert [m.content for m in latest] == [str(i) for i in range(105, 205)]
    older = db.list_message_records(conversation, before=latest[0].position)
    assert [m.content for m in older] == [str(i) for i in range(5, 105)]
    oldest = db.list_message_records(conversation, before=older[0].position)
    assert [m.content for m in oldest] == [str(i) for i in range(5)]
    assert db.list_message_records(conversation, before=oldest[0].position) == []
    forward = db.list_message_records(conversation, after=older[-1].position)
    assert [m.id for m in forward] == [m.id for m in latest]
    assert len({m.id for m in [*oldest, *older, *latest]}) == 205
    with TestClient(
        create_app(database_path=Path(db.path), registry=ProviderRegistry([])),
        base_url="http://127.0.0.1",
    ) as client:
        url = f"/conversations/{conversation}/messages"
        assert [m["id"] for m in client.get(url, params={"tail": True}).json()] == [
            m.id for m in latest
        ]
        for params in [
            {"after": 1, "tail": True},
            {"before": 3, "after": 1},
            {"before": 1, "tail": True},
            {"before": 0},
            {"limit": 501},
        ]:
            assert client.get(url, params=params).status_code == 422
        assert (
            client.get(url, params={"before": older[0].position}).json()[0]["content"]
            == "0"
        )


def test_ui_static_path_cannot_escape_to_data(tmp_path):
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("UI")
    (tmp_path / "secret.txt").write_text("not-a-static-asset")
    (ui / "outside.txt").symlink_to(tmp_path / "secret.txt")
    app = create_app(
        database_path=tmp_path / "chat.db",
        registry=ProviderRegistry([]),
        ui_directory=ui,
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/ui/outside.txt").status_code == 404
        assert client.get("/ui/%2e%2e/secret.txt").status_code == 404
