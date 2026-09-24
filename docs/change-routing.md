# Change Routing

| 変更 | 主なsource | 最初のtests |
|---|---|---|
| Character / prompt budget | `models.py`, `prompting.py` | `tests/test_runtime.py` |
| Recall / Guardian | `recall.py`, `guardian.py` | `tests/test_recall.py`, `tests/test_guardian.py`, `tests/test_runtime.py` |
| rolling summary | `summary.py`, `models.py` | `tests/test_summary.py`, `tests/test_long_turn.py` |
| SQLite / migration / atomicity | `storage.py` | `tests/test_storage.py`, `tests/test_runtime.py`, `tests/test_long_turn.py` |
| chat / repair / timeout | `service.py` | `tests/test_service.py`, `tests/test_runtime.py` |\n| generation status / streaming / Stop | `models.py`, `storage.py`, `service.py`, `api.py`, `frontend/src/` | `tests/test_generation_status.py`, `frontend/e2e/chat.spec.ts`, 全pytest |
| Provider protocol | `providers.py` | `tests/test_provider_streams.py` |
| API / localhost boundary | `api.py` | `tests/test_api.py`, `tests/test_long_turn.py` |
| UI / HTTP client / loading state | `frontend/src/` | TypeScript build、`frontend/e2e/chat.spec.ts` |
| static UI / history windows | `webui.py`, `api.py`, `storage.py` | `tests/test_webui.py`、全pytest |
| workflow / packaging | `pyproject.toml`, `.github/workflows/ci.yml` | 全pytest、Ruff、installed wheel smoke |

sourceのルートは `src/character_chat_local/`。共通model、永続化、API契約を変えたら全suiteへ広げる。
UIの起動・検証は `webui.md`。UI taskの原典はADR-0002とIssue #10。無関係なsourceや全Issuesを先読みしない。
