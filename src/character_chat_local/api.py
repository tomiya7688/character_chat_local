from __future__ import annotations

import hmac
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .models import CharacterCore, MemoryRecord
from .providers import ProviderError, ProviderRegistry
from .service import ChatService, QualityRejected
from .storage import ConversationConflict, Storage


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    character_id: str = Field(min_length=1, max_length=200)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    user_input: str = Field(min_length=1, max_length=4000)
    temperature: float = Field(default=0.8, ge=0, le=2)


def create_app(
    *,
    database_path: str | Path | None = None,
    registry: ProviderRegistry | None = None,
    allowed_origins: tuple[str, ...] = (),
    api_token: str | None = None,
) -> FastAPI:
    """Local-only API. Instantiation/import does not open a database or a provider."""
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        path = database_path or os.getenv("CHARACTER_CHAT_DB", "data/chat.sqlite3")
        app.state.storage = Storage(path)
        app.state.registry = registry if registry is not None else ProviderRegistry.from_env()
        app.state.service = ChatService(app.state.storage)
        app.state.active = set()
        app.state.api_token = api_token if api_token is not None else os.getenv("CHARACTER_CHAT_API_TOKEN")
        yield
        app.state.active.clear()

    app = FastAPI(title="character_chat_local", lifespan=lifespan)
    if allowed_origins:
        app.add_middleware(
            CORSMiddleware, allow_origins=list(allowed_origins),
            allow_methods=["GET", "POST", "PUT"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        if request.url.hostname not in {"localhost", "127.0.0.1", "::1"}:
            return JSONResponse({"detail": "invalid host"}, status_code=400)
        origin = request.headers.get("origin")
        same_origin = f"{request.url.scheme}://{request.headers.get('host', '')}"
        if origin and origin not in {same_origin, *allowed_origins}:
            return JSONResponse({"detail": "origin not allowed"}, status_code=403)
        # Browsers may omit Origin on navigations. Reject cross-site fetches as well.
        if request.headers.get("sec-fetch-site") == "cross-site" and origin not in allowed_origins:
            return JSONResponse({"detail": "cross-site request not allowed"}, status_code=403)
        token = getattr(app.state, "api_token", None)
        preflight = request.method == "OPTIONS" and origin in allowed_origins
        if token and request.url.path != "/health" and not preflight:
            supplied = request.headers.get("authorization", "")
            if not hmac.compare_digest(supplied.encode(), f"Bearer {token}".encode()):
                return JSONResponse({"detail": "authorization required"}, status_code=401)
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        # Do not reflect raw request bodies (which may accidentally contain a secret).
        return JSONResponse({"detail": [
            {"loc": e["loc"], "type": e["type"], "msg": e["msg"]} for e in exc.errors()
        ]}, status_code=422)

    @app.exception_handler(ProviderError)
    async def provider_error(request: Request, exc: ProviderError):
        return JSONResponse({"detail": {"code": "provider_error", "message": "Provider request failed. Check the local provider configuration."}}, status_code=502)

    @app.exception_handler(ConversationConflict)
    async def conversation_conflict(request: Request, exc: ConversationConflict):
        return JSONResponse({"detail": "conversation changed; retry"}, status_code=409)

    def storage() -> Storage:
        return app.state.storage

    def character_or_404(character_id: str) -> CharacterCore:
        character = storage().load_character(character_id)
        if character is None:
            raise HTTPException(404, "character not found")
        return character

    def conversation_or_404(conversation_id: str):
        try:
            return storage().get_conversation(conversation_id)
        except KeyError:
            raise HTTPException(404, "conversation not found") from None

    def provider_or_404(provider_id: str):
        try:
            return app.state.registry.get(provider_id)
        except ProviderError:
            raise HTTPException(404, "provider not configured") from None

    def validate_character(character: CharacterCore):
        if not character.name.strip() or len(character.model_dump_json().encode()) > 12_000:
            raise HTTPException(422, "character must have a name and fit within 12000 UTF-8 bytes")

    @app.get("/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/characters")
    def list_characters(limit: int = Query(100, ge=1, le=500)):
        return storage().list_characters(limit)

    @app.post("/characters", status_code=201)
    def create_character(character: CharacterCore):
        validate_character(character)
        if storage().load_character(character.id):
            raise HTTPException(409, "character already exists; use PUT")
        storage().save_character(character)
        return character

    @app.get("/characters/{character_id}")
    def get_character(character_id: str):
        return character_or_404(character_id)

    @app.put("/characters/{character_id}")
    def update_character(character_id: str, character: CharacterCore):
        character_or_404(character_id)
        if character.id != character_id:
            raise HTTPException(422, "character ID does not match path")
        validate_character(character)
        storage().save_character(character)
        return character

    @app.get("/conversations")
    def list_conversations(limit: int = Query(100, ge=1, le=500)):
        return storage().list_conversations(limit)

    @app.post("/conversations", status_code=201)
    def create_conversation(payload: ConversationCreate):
        character_or_404(payload.character_id)
        return storage().get_conversation(storage().create_conversation(payload.character_id))

    @app.get("/conversations/{conversation_id}/messages")
    def get_messages(conversation_id: str, after: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)):
        conversation_or_404(conversation_id)
        return storage().list_message_records(conversation_id, after=after, limit=limit)

    @app.get("/conversations/{conversation_id}/summary")
    def get_summary(conversation_id: str):
        conversation_or_404(conversation_id)
        return storage().get_summary(conversation_id)

    @app.get("/characters/{character_id}/memories")
    def get_memories(character_id: str):
        character_or_404(character_id)
        return storage().list_memories(character_id)

    @app.post("/characters/{character_id}/memories", status_code=201)
    def save_memory(character_id: str, memory: MemoryRecord):
        character_or_404(character_id)
        if memory.character_id != character_id or not memory.content.strip():
            raise HTTPException(422, "invalid memory character or content")
        if len(memory.model_dump_json().encode()) > 8000:
            raise HTTPException(422, "memory exceeds size limit")
        try:
            storage().upsert_memory(memory)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        return memory

    @app.get("/providers")
    def list_providers():
        return {"providers": app.state.registry.ids()}

    @app.get("/providers/{provider_id}/models")
    async def get_models(provider_id: str):
        provider = provider_or_404(provider_id)
        try:
            models = await provider.list_models()
        except (ProviderError, httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
            raise ProviderError("model discovery failed") from exc
        # Do not expose arbitrary provider metadata or credentials to the frontend.
        return [{"id": m.id, "provider": m.provider, "display_name": m.display_name} for m in models]

    @app.post("/conversations/{conversation_id}/chat")
    async def chat(conversation_id: str, payload: ChatRequest):
        conversation = conversation_or_404(conversation_id)
        character = character_or_404(conversation.character_id)
        provider = provider_or_404(payload.provider)
        if conversation_id in app.state.active:
            raise HTTPException(409, "conversation is already generating")
        app.state.active.add(conversation_id)
        try:
            result = await app.state.service.run(
                provider=provider, model=payload.model, character=character,
                user_input=payload.user_input, conversation_id=conversation_id,
                temperature=payload.temperature,
            )
        except QualityRejected as exc:
            raise HTTPException(422, {
                "code": "quality_rejected", "message": "No response passed quality checks.",
                "evaluation_id": exc.evaluation_id,
            }) from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        finally:
            app.state.active.discard(conversation_id)
        # Deliberately buffered: never stream an unvalidated draft to a client.
        return {
            "conversation_id": conversation_id, "provider": payload.provider,
            "model": payload.model, "text": result.text, "guardian": result.guardian,
            "repaired": result.repaired,
            "regenerated_for_recall": result.regenerated_for_recall,
        }

    return app


app = create_app()
