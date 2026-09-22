"""Deterministic application endurance, NOT evidence of real LLM conversation quality."""

import json

from fastapi.testclient import TestClient

from character_chat_local.api import create_app
from character_chat_local.models import ModelInfo
from character_chat_local.prompting import prompt_size
from character_chat_local.providers import AIProvider, ProviderRegistry
from character_chat_local.storage import Storage


class AuditingProvider(AIProvider):
    def __init__(self, provider_id):
        self.id = provider_id
        self.count = 0
        self.largest_prompt = 0

    async def list_models(self):
        return [ModelInfo(id="tiny", provider=self.id)]

    async def stream_chat(self, *, model, messages, temperature=0.8):
        self.count += 1
        assert model in {"tiny", "other-model"}
        size = prompt_size(messages)
        self.largest_prompt = max(size, self.largest_prompt)
        assert size <= 24000 and len(messages) <= 14
        assert "海辺の町" in messages[0].content
        yield "確認: " + messages[-1].content


def test_1000_roundtrips_restart_model_switch_and_provenance(tmp_path):
    path = tmp_path / "endurance.db"
    providers = [AuditingProvider("audit-a"), AuditingProvider("audit-b")]
    registry = ProviderRegistry(providers)
    conversation = character_id = None
    for phase in range(2):
        app = create_app(database_path=path, registry=registry)
        with TestClient(app, base_url="http://127.0.0.1") as client:
            if phase == 0:
                character = client.post(
                    "/characters", json={"name": "ミカ", "lore": ["海辺の町"]}
                ).json()
                character_id = character["id"]
                conversation = client.post(
                    "/conversations", json={"character_id": character_id}
                ).json()["id"]
            for turn in range(phase * 500, (phase + 1) * 500):
                text = (
                    "私の名前はカドカ。約束を覚えてね" if turn == 0 else f"会話 {turn}"
                )
                response = client.post(
                    f"/conversations/{conversation}/chat",
                    json={
                        "provider": providers[phase].id,
                        "model": "tiny" if phase == 0 else "other-model",
                        "user_input": text,
                    },
                )
                assert response.status_code == 200, (turn, response.text)
                assert response.json()["text"] == "確認: " + text
            # The other conversation cannot inherit this conversation's extracts.
            other = client.post(
                "/conversations", json={"character_id": character_id}
            ).json()["id"]
            assert client.get(f"/conversations/{other}/summary").json()["entries"] == []
    storage = Storage(path)
    summary = storage.get_summary(conversation)
    assert summary.covered_messages == 1986
    assert len(summary.entries) <= 12
    assert "カドカ" in summary.entries[0].excerpt
    assert storage.get_conversation(conversation).revision == 1000
    with storage.session() as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert (
            db.execute(
                "SELECT count(*) FROM messages WHERE conversation_id=?", (conversation,)
            ).fetchone()[0]
            == 2000
        )
        assert (
            db.execute("SELECT count(*) FROM response_evaluations").fetchone()[0]
            == 1000
        )
        for entry in summary.entries:
            row = db.execute(
                "SELECT content, role FROM messages WHERE id=?",
                (entry.source_message_id,),
            ).fetchone()
            assert entry.excerpt == row["content"][:160] and entry.role == row["role"]
        rows = db.execute(
            "SELECT model, count(*) AS count FROM messages WHERE role='assistant' GROUP BY model"
        ).fetchall()
        assert {row["model"]: row["count"] for row in rows} == {
            "tiny": 500,
            "other-model": 500,
        }
    assert [p.count for p in providers] == [500, 500]
    report = {
        "turns": 1000,
        "messages": 2000,
        "covered_messages": summary.covered_messages,
        "max_prompt_bytes": max(p.largest_prompt for p in providers),
        "real_inference": False,
    }
    (tmp_path / "endurance-result.json").write_text(
        json.dumps(report), encoding="utf-8"
    )
