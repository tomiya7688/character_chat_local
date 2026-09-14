# Current State

最終更新: 2026-09-14

## Implemented
- Python/FastAPI のローカルバックエンド骨格と `/health`
- 共通 `AIProvider` interface
- Ollama provider
- OpenAI互換 provider（OpenAI / xAI向け）
- Gemini REST provider
- SQLite persistence（character / conversation / message / memory / evaluation）
- 最小Character prompt composition
- trigger / entity / lexical / importance / confidence を使う軽量Recall
- Draftを使うSecondary Recall
- Secondary Recallで新規Memoryが見つかった場合の最大1回再生成
- heuristic Guardian（meta leak / repetition / user-control / forbidden phrase）
- Recall / Guardian / Storage / orchestration のunit tests
- pull request CI

## Explicitly Not Implemented Yet
- Character / Memory / Chat の完全なHTTP API surface
- Guardian fail時のRepair / Regenerate
- Tauri / React UI
- embedding / vector search
- LLMによるMemory extraction / state extraction
- OS credential store
- provider abort API
- production-grade token counting
- advanced lore contradiction detection
- edit & retry / conversation branching
- LoRA / DPO export

## Architecture Decision for v0.1
- Desktop shell/UI: Tauri + React/TypeScript（後続）
- Local service: FastAPI/Python
- Persistence: SQLite, stdlib `sqlite3` から開始
- Frontend/backend: localhost HTTP + streaming APIへ拡張
- Provider boundary: Python `AIProvider`
- Vector DBは初期依存にせず、Recall interfaceの内部実装として後から追加

## Current Validation Boundary
Pure logic / SQLiteはunit test対象。Ollama / OpenAI / Gemini / xAI実接続はcredentialやローカルdaemonに依存するためCIではmockまたは未接続とし、実API smokeは別途行う。
