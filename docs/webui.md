# Local WebUI

React + Vite + TypeScript strict。Tauriなしで利用でき、会話・品質判定・保存はPython側が担当する。
設計の原典: ADR-0002、Issue #10 / #45。公開DTOの原典は `models.py` / `api.py`。

## Build and run

Python 3.11以上、ビルド時だけNode.js 22.12以上が必要。

```bash
python -m pip install -e '.[dev]'
cd frontend
npm ci
npm run build
cd ..
python -m uvicorn character_chat_local.api:app --host 127.0.0.1 --port 8765 --workers 1
```

`http://127.0.0.1:8765/ui/` を開く。Ollama daemonとモデルは別途必要。
画面の「追加」でキャラクターを作成するか、`examples/characters/mika.json` を読み込み、保存する。
モデルを選び「新しい会話」から開始する。モデル一覧に出ないIDは「IDを直接指定」で入力できる。

build先は `src/character_chat_local/webui/`。このディレクトリは生成物としてGitから除外する。
`python -m pip wheel . --no-deps --wheel-dir dist` でbuild済みassetsを含むwheelを作れる。
ソースだけから作ったwheelにはUIを含めず、backend単独利用は継続して可能。
任意の既存buildを配信する場合は `CHARACTER_CHAT_UI_DIR` をそのディレクトリに設定する（index.html必須）。

## Frontend development

別ターミナルで次を実行する。開発用の許可Originは5173のloopbackのみ。

```bash
python -m uvicorn tools.webui_dev:app --host 127.0.0.1 --port 8765 --workers 1
```

```bash
cd frontend
npm ci
npm run dev
```

開発UIは `http://127.0.0.1:5173/ui/`。
開発時の既定API URLは `.env.development` の `VITE_API_BASE_URL=http://127.0.0.1:8765`。
変更する場合はGit対象外の `.env.development.local` で指定し、backend側のexact Origin設定も合わせる。
本番buildは同一Originから配信する。別Originへの本番接続はCSPで許可していない。
`VITE_*` はブラウザへ公開されるため、APIキーやトークンを入れない。

## Security / state

`CHARACTER_CHAT_API_TOKEN` をbackendで設定した場合、画面の「接続設定」にローカルAPIトークンを入力する。
タブのメモリだけで保持し、localStorage / sessionStorage / URL / DBへ保存しない。
ページを再読込したら再入力が必要。ProviderのAPIキーはbackendの環境変数から設定する。
認証前に配信するのは静的な `/ui/` シェルとassetsのみで、会話APIは引き続き認証される。
Host / Origin / Fetch Metadata確認、CSP、静的ファイルのディレクトリ境界を維持する。

会話履歴はDBを原本とし、品質を通過した応答だけを表示する。失敗した入力を確定履歴として表示しない。
品質不合格では入力を保持する。通信結果が不明な場合は勝手に再送しない。履歴再読込で保存状況を確認してから操作する。
同一タブで送信中はモデル/会話/設定変更を抑止する。タブを閉じても推論を確実に停止できるとは限らない。
Stop APIは未実装なので、単なるHTTP abortを「停止」と呼ぶボタンは設けない。

Markdownはraw HTMLを許可せず、標準のURL sanitizationを使用する。外部画像はテキストに置き換え、自動取得しない。
会話の抜粋要約は意味を完全には保持しない。「出典を見る」で元メッセージへ移動できる。

## Validation

```bash
python -m pytest -q tests/test_webui.py
python -m pytest -q
cd frontend
npm ci
npm run build
npx playwright install --with-deps chromium
npm run test:e2e
```

ブラウザテストは `tools/webui_e2e_server.py` を自動起動する。localhost:8766を空けておく。
使うのは一時DBと決定的Providerで、実Ollama/外部APIやユーザーの保存済みDBには接続しない。
期待出力、draft streaming、Stop非保存、品質拒否/修正、model切替、reload、IME、重複submit、2,000メッセージのwindow、認証、Markdown、mobile、要約出典を確認する。
CIのfrontend jobでも同じ操作を実行し、JUnit / HTML report / screenshotと、WebUI同梱wheelをartifactに保存する。
成功ログ全文ではなく結果を確認し、失敗時だけ対象trace/差分を見る。

## Still outside this increment

Regenerate/Edit/retry、外部character-card形式、一覧500件を超える検索、OS keychain、Tauri配布。streamingはPOST + NDJSONで実装し、SSEは採用していない。
未送信入力の会話間保持・リロード後復元も未実装。Providerは模擬実装で検証するため、実モデル品質・GPU性能・本人の使用テストは別の受入条件。
