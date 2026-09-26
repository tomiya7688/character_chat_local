import asyncio

import httpx
import pytest
from conftest import ScriptedProvider
from fastapi.testclient import TestClient

from character_chat_local.api import create_app
from character_chat_local.providers import ProviderRegistry


@pytest.fixture
def client(tmp_path, provider):
    app = create_app(
        database_path=tmp_path / "api.db", registry=ProviderRegistry([provider])
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        yield client


def new_conversation(client):
    character = client.post(
        "/characters", json={"name": "ミカ", "first_person": "私"}
    ).json()
    response = client.post("/conversations", json={"character_id": character["id"]})
    assert response.status_code == 201
    return character, response.json()["id"]


def send(client, conversation, **kwargs):
    return client.post(
        f"/conversations/{conversation}/chat",
        json={
            "provider": "fake",
            "model": "small",
            "user_input": "こんにちは",
            **kwargs,
        },
    )


def test_character_model_selection_chat_history_and_update(client, provider):
    character, conversation = new_conversation(client)
    assert client.get("/providers").json() == {"providers": ["fake"]}
    assert len(client.get("/providers/fake/models").json()) == 2
    assert send(client, conversation).status_code == 200
    response = send(client, conversation, model="other")
    assert response.status_code == 200
    assert "draft" not in response.json() and "primary_recall" not in response.json()
    messages = client.get(f"/conversations/{conversation}/messages?limit=2").json()
    assert len(messages) == 2 and messages[1]["model"] == "small"
    page2 = client.get(
        f"/conversations/{conversation}/messages?after={messages[-1]['position']}"
    ).json()
    assert len(page2) == 2 and page2[1]["model"] == "other"
    assert len(client.get("/conversations").json()) == 1
    assert len(client.get("/characters").json()) == 1
    character["speech_style"] = ["ゆっくり"]
    assert (
        client.put(f"/characters/{character['id']}", json=character).status_code == 200
    )
    assert client.get(f"/characters/{character['id']}").json()["speech_style"] == [
        "ゆっくり"
    ]
    assert [c[0] for c in provider.calls] == ["small", "other"]


def test_failed_draft_never_returned_or_saved(client, provider):
    _, conversation = new_conversation(client)
    provider.replies = ["AIとして、private-draft-canary"]
    response = send(client, conversation)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "quality_rejected"
    assert "private-draft-canary" not in response.text
    assert client.get(f"/conversations/{conversation}/messages").json() == []


def test_provider_errors_are_sanitized(client, provider):
    _, conversation = new_conversation(client)
    provider.replies = [httpx.ReadError("secret-provider-canary")]
    response = send(client, conversation)
    assert response.status_code == 502
    assert "secret-provider-canary" not in response.text
    assert client.get(f"/conversations/{conversation}/messages").json() == []
    assert send(client, conversation, provider="missing").status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"user_input": "  "},
        {"temperature": -1},
        {"user_input": "x" * 4001},
        {"history": []},
    ],
)
def test_invalid_chat_is_rejected_before_generation(client, provider, payload):
    _, conversation = new_conversation(client)
    assert send(client, conversation, **payload).status_code == 422
    assert not provider.calls


def test_nonexistent_and_mismatched_resources(client):
    character, conversation = new_conversation(client)
    assert send(client, "missing").status_code == 404
    assert (
        client.post("/conversations", json={"character_id": "missing"}).status_code
        == 404
    )
    assert client.get("/characters/missing").status_code == 404
    assert client.post("/characters", json=character).status_code == 409
    assert (
        client.post(
            f"/characters/{character['id']}/memories",
            json={"character_id": "other", "type": "canon", "content": "test"},
        ).status_code
        == 422
    )
    assert (
        client.get(f"/conversations/{conversation}/summary").json()["strategy"]
        == "extractive-v1"
    )


def test_memory_source_must_belong_to_character(client):
    character, conversation = new_conversation(client)
    other, _ = new_conversation(client)
    send(client, conversation)
    source = client.get(f"/conversations/{conversation}/messages").json()[0]["id"]
    payload = {
        "character_id": character["id"],
        "type": "user_fact",
        "content": "明示情報",
        "source_message_id": source,
    }
    assert (
        client.post(f"/characters/{character['id']}/memories", json=payload).status_code
        == 201
    )
    payload["character_id"] = other["id"]
    assert (
        client.post(f"/characters/{other['id']}/memories", json=payload).status_code
        == 422
    )


def test_local_origin_host_and_fetch_metadata_boundaries(client):
    assert client.get("/health").json() == {"ok": True}
    assert (
        client.get(
            "/health", headers={"Origin": "https://untrusted.example"}
        ).status_code
        == 403
    )
    assert (
        client.get("/health", headers={"Host": "untrusted.example"}).status_code == 400
    )
    assert (
        client.get("/characters", headers={"Sec-Fetch-Site": "cross-site"}).status_code
        == 403
    )
    assert (
        client.get("/characters", headers={"Origin": "http://127.0.0.1"}).status_code
        == 200
    )


def test_optional_token_and_import_without_database_side_effect(tmp_path):
    path = tmp_path / "api.db"
    app = create_app(
        database_path=path, registry=ProviderRegistry([]), api_token="test-token"
    )
    assert not path.exists()
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/health").status_code == 200
        assert client.get("/characters").status_code == 401
        assert (
            client.get(
                "/characters", headers={"Authorization": "Bearer test-token"}
            ).status_code
            == 200
        )


async def test_parallel_send_is_rejected_without_extra_generation(tmp_path):
    started, release = asyncio.Event(), asyncio.Event()

    class Blocking(ScriptedProvider):
        async def stream_chat(self, **kwargs):
            self.calls.append(kwargs)
            started.set()
            await release.wait()
            yield "こんにちは。"

    provider = Blocking()
    app = create_app(
        database_path=tmp_path / "parallel.db", registry=ProviderRegistry([provider])
    )
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client,
    ):
        character = (await client.post("/characters", json={"name": "ミカ"})).json()
        created = await client.post(
            "/conversations", json={"character_id": character["id"]}
        )
        conversation = created.json()["id"]
        url = f"/conversations/{conversation}/chat"
        payload = {"provider": "fake", "model": "small", "user_input": "hello"}
        first = asyncio.create_task(client.post(url, json=payload))
        await asyncio.wait_for(started.wait(), timeout=3)
        second = await client.post(url, json=payload)
        assert second.status_code == 409
        release.set()
        assert (await first).status_code == 200
        assert len(provider.calls) == 1 and not app.state.active


def test_explicit_dev_origin_and_token_preflight(tmp_path):
    app = create_app(
        database_path=tmp_path / "cors.db",
        registry=ProviderRegistry([]),
        allowed_origins=("http://localhost:5173",),
        api_token="token",
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        headers = {"Origin": "http://localhost:5173", "Sec-Fetch-Site": "cross-site"}
        preflight = client.options(
            "/characters",
            headers={
                **headers,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization,Content-Type",
            },
        )
        assert preflight.status_code == 200
        assert client.get("/characters", headers=headers).status_code == 401
        response = client.get(
            "/characters", headers={**headers, "Authorization": "Bearer token"}
        )
        assert response.status_code == 200
        assert (
            response.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
        )


def test_quality_mode_overrides_are_persisted_and_reported(client, provider):
    character = client.post(
        "/characters",
        json={"name": "Mode", "quality_mode": "strict"},
    ).json()
    conversation = client.post(
        "/conversations", json={"character_id": character["id"]}
    ).json()["id"]

    inherited = send(client, conversation)
    assert inherited.status_code == 200
    assert inherited.json()["quality_mode"] == "strict"

    updated = client.put(
        f"/conversations/{conversation}/quality-mode",
        json={"quality_mode": "fast"},
    )
    assert updated.status_code == 200
    assert updated.json()["quality_mode"] == "fast"
    assert send(client, conversation).json()["quality_mode"] == "fast"

    cleared = client.put(
        f"/conversations/{conversation}/quality-mode",
        json={"quality_mode": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["quality_mode"] is None
    assert send(client, conversation).json()["quality_mode"] == "strict"


def test_global_quality_mode_is_used_when_no_override(tmp_path, provider):
    app = create_app(
        database_path=tmp_path / "mode.db",
        registry=ProviderRegistry([provider]),
        default_quality_mode="fast",
    )
    with TestClient(app, base_url="http://127.0.0.1") as mode_client:
        _, conversation = new_conversation(mode_client)
        response = send(mode_client, conversation)
        assert response.status_code == 200
        assert response.json()["quality_mode"] == "fast"
