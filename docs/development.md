# Development

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

## Run

```bash
uvicorn character_chat_local.api:app --reload --port 8765
```

The current HTTP surface is intentionally minimal. `/health` is available first; domain APIs are added as the service boundary stabilizes.

## Test

```bash
python -m pytest -q
```

Start with the matching test for the changed module. Run the full unit suite when shared models, storage, recall orchestration, or provider contracts change.

## Provider environment

- Ollama: `OLLAMA_BASE_URL` (default `http://127.0.0.1:11434`)
- OpenAI: `OPENAI_API_KEY`, optional `OPENAI_BASE_URL`
- Gemini: `GEMINI_API_KEY`
- xAI: `XAI_API_KEY`, optional `XAI_BASE_URL`

Do not commit credentials or persist them into the application database.
