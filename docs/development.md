# Development

## Setup / run

Python 3.11以上。仮想環境を有効化してから実行する。

```bash
python -m pip install -e '.[dev]'
python -m uvicorn character_chat_local.api:app --host 127.0.0.1 --port 8765 --workers 1
```

`http://127.0.0.1:8765/docs` はAPI操作用のSwagger UI。
React UIはfrontendをbuildしてから `http://127.0.0.1:8765/ui/` で利用する。
ビルド・開発サーバー・ブラウザテストの手順は [WebUI](webui.md) を参照。
Ollama daemonと会話用modelは別途必要。`GET /providers/ollama/models` で利用可能なmodel IDを確認する。

## API flow

1. `POST /characters` に `{"name":"ミカ","first_person":"私","speech_style":["穏やか"],"lore":["海辺の町に住む"]}` を送る。
2. 返ったCharacter IDを使い `POST /conversations` に `{"character_id":"<id>"}` を送る。
3. 返ったConversation IDへ、bufferedなら `POST /conversations/<id>/chat`、WebUI相当の逐次表示なら `POST /conversations/<id>/chat/stream` を送る。

```json
{"provider":"ollama","model":"<installed-model-id>","user_input":"こんにちは","temperature":0.8}
```

Provider/modelは毎回選べる。履歴とキャラクターの対応はサーバーが復元し、クライアントからのhistoryは受け付けない。
buffered `/chat` は成功時に最終text、provider/model、Guardian結果、修正有無だけを返す。`/chat/stream` はNDJSONで `started` / `draft_delta` / `phase` / `final` / `stopped` / `error` を返し、初回draftだけを未確定previewとして扱う。branch系streamでは `started.conversation_id` が新branch IDになり、StopにもそのIDを使う。

| Endpoint | 用途 |
|---|---|
| `GET /characters`, `GET /characters/{id}`, `PUT /characters/{id}` | Character一覧・取得・更新（PUTはIDを含む完全な定義） |
| `GET /conversations` | 会話一覧 |
| `GET /conversations/{id}/messages?after=0&limit=100` | 昇順の履歴。次ページは最後のpositionをafterへ渡す。`tail=true`は最新、`before=<position>`は直前のページ（どちらも返却順は昇順）。cursorの併用は禁止。limitは最大500 |
| `GET /conversations/{id}/summary` | 出典付き抽出要約と処理済み件数 |
| `GET /characters/{id}/memories`, `POST /characters/{id}/memories` | 構造化Memory。source指定時は同一characterのmessage IDが必要 |
| `GET /providers`, `GET /providers/{id}/models` | 設定済みProvider / model一覧。credentialは返さない |
| `POST /conversations/{id}/chat/stream` | NDJSONで初回draft previewと検証状態を配信し、最後に確定Finalを返す |
| `POST /conversations/{id}/generations/{generation_id}/stop` | 実行中provider taskを停止。停止turnは確定履歴へcommitしない |
| `POST /conversations/{id}/messages/{assistant_id}/regenerate/stream` | assistant発言の直前user turnから新branchを生成する。bodyはprovider/model/temperature |
| `POST /conversations/{id}/messages/{user_id}/edit-retry/stream` | user発言の直前までをbranchし、bodyのuser_inputで再生成する |

404は未知のリソース/未設定Provider、409は同時生成・revision競合、422は入力/budget/品質不合格、502はProvider失敗。
`quality_rejected` の場合はevaluation IDのみ返し、不合格textを確定履歴へ追加しない。
通常chatのネットワークエラー・timeout・キャンセル時も途中のturnを保存しない。branch系操作は成功するまでpendingとして一覧から隠し、失敗/Stopではpending branchを破棄する。元conversationのmessageは更新・削除しない。

## Settings / security

- DB: `CHARACTER_CHAT_DB`（既定 `data/chat.sqlite3`）。起動前に旧DBをバックアップする。migrationは列/テーブルの追加のみ。
- Ollama: `OLLAMA_BASE_URL`（既定 `http://127.0.0.1:11434`）。
- OpenAI: `OPENAI_API_KEY`, 任意の `OPENAI_BASE_URL`（API root、`/v1`を含めない）。
- xAI: `XAI_API_KEY`, 任意の `XAI_BASE_URL`（API root）。Gemini: `GEMINI_API_KEY`。
- 任意のローカル認証: `CHARACTER_CHAT_API_TOKEN`。設定時はAPIに `Authorization: Bearer <token>` が必要。`/health` と `GET/HEAD /ui[/...]` の静的シェルだけは認証不要（Host/Origin確認は維持）。

APIキーはbackendの環境変数から渡す。DBやfrontendに設定用credentialを保存しない。
Host/Origin/Fetch Metadataチェックはブラウザからの不意のアクセスを抑えるもので、OSの他プロセスに対する認証の代わりではない。
LANへbindしない。開発用frontendを別portで使う場合だけ、`create_app(allowed_origins=("http://127.0.0.1:5173",))` のようにexact originを明示する。

## Context / quality limits

通常生成1回 + Secondary Recall再生成1回 + 品質修正1回が上限。total generation timeoutは既定300秒、各出力は最大8,000文字。
`ChatService(max_prompt_bytes=...)` はUTF-8 bytesとmessage overheadによる上限（既定24,000）であり、モデル固有のtoken数保証ではない。
小さいcontext windowのmodelには予算調整が必要。固定設定や現在入力を黙って切り捨てず、収まらなければエラーとする。
抽出型要約の精度と実LLMの会話品質は別途評価する。詳細は `current-state.md`。

## Validation

```bash
python -m pytest -q tests/test_api.py tests/test_runtime.py
python -m pytest -q tests/test_summary.py tests/test_long_turn.py
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
```

1,000往復テストは実際のHTTP APIとSQLiteを使い、Providerのみ決定的な模擬実装に置き換える。
GPUやAPIキーは不要。保存・復元・budget・期待出力を確認するが、実モデルの人格維持率や性能の証拠にはしない。
通常CIのPython 3.11/3.12で全テストを走らせ、wheelをインストールした別作業ディレクトリでもAPI起動をsmokeする。
CI artifactはJUnit結果とRuffの差分。失敗時だけ対象箇所を読み、成功ログ全文をAIへ渡さない。
