# AI Context

`ai-context-reducer` の最小コアを適用する開発入口。仕様をここへ複製しない。

## Source of Truth
- 設計判断: `docs/adr/` の該当ADR。製品の狙い: `README.md`。
- 実装済み / 未検証: `docs/current-state.md`。
- 変更対象 / 検証: `docs/change-routing.md`、対象sourceとtests。
- 起動・API・設定: `docs/development.md`。WebUIのbuild/実行/検証: `docs/webui.md`。
- 現在タスク / Acceptance: 対応するGitHub Issue。

## Working Rules
- Goal / Required / Acceptance が揃ったら探索を止める。
- Search first, read second。target source -> matching tests -> 必要な原典。
- 全Issues、全履歴、無関係な文書を一括で読まない。
- 要約は索引。食い違いは原典・実行結果で確認する。
- unrelated refactorを混ぜない。shared contract変更時は全テストへ広げる。
- 複数セッションがremoteを更新するため、編集前にfetchしcommit要約・変更ファイルを確認する。
  他者の変更をforce pushや無条件の置換で消さない。

## Invariants
- Character Core / Canonを会話要約や推測で上書きしない。
- 要約は会話単位。Memoryのsourceは同一characterに所属する。
- buffered `/chat` は不合格draftを返さない。`/chat/stream` の初回draft previewは未確定と明示し、保存・Memory/State更新の正本にしない。Finalだけを確定会話へcommitする。
- 再生成は有限。通常1回、追加Recall1回、品質修正1回まで。
- Regenerate / Edit & Retry は既存messageをUPDATE/DELETEしない。元会話を不変に保ち、prefixをpending branchへ複製し、Final成功時だけbranchを公開する。
- branch成功時だけ置換対象の旧generationを `superseded` にする。Stop/失敗時はpending branchを破棄し、元会話を正本のまま残す。
- 保存はturn単位で原子的に行う。推論中にSQLite書込lockを保持しない。
- Credentialはbackendの設定。frontend、DB、エラーへ設定値を流さない。
- WebUIが本体、Tauriは後続の配布ラッパー。domain logicをUIへ移さない。

## Validation
- まず `docs/change-routing.md` の該当テスト。
- 共通契約変更: `python -m pytest -q`、`python -m ruff check .`、`python -m ruff format --check .`。
- CIはPython 3.11 / 3.12、1,000往復の決定的HTTPテスト、wheelインストール後のsmoke。
- 成功ログ全文ではなく、結果・対象commit・未検証領域を報告する。
- UI変更: `cd frontend && npm ci && npm run build && npm run test:e2e`。
- ブラウザE2EはAPI/SQLiteの実処理と模擬Providerを使う。実モデル品質や本人の使用テストとは分ける。

## Ignore Normally
`.venv/`, caches, `data/`, DB/WAL files, `dist/`, generated reports, unrelated history。

## Adoption
参照: https://github.com/tomiya7688/ai-context-reducer
採用: Core入口、Current State、Change Routing、Remote Delta、targeted validation、artifact smoke。
見送り: 巨大索引、call graph、階層ガイド、大きいContext Pack。小規模repoでは維持コストが上回る。
