# Change Routing

Start from the current Issue, then read only the matching source and tests.

| Change | Source | Tests |
|---|---|---|
| provider / model API | `src/character_chat_local/providers.py` | provider smoke / targeted tests |
| character schema | `models.py` | matching model/prompt tests |
| prompt composition | `prompting.py` | prompt tests |
| recall | `recall.py` | `tests/test_recall.py`, `tests/test_service.py` |
| guardian | `guardian.py` | `tests/test_guardian.py` |
| persistence | `storage.py` | `tests/test_storage.py` |
| orchestration | `service.py` | `tests/test_service.py` |
| HTTP surface | `api.py` | API tests when endpoints are added |

Stop broad exploration once the current task's Goal, Required evidence, and Acceptance are satisfied. Run the matching test first; run the full unit suite for shared contracts.
