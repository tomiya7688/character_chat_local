# Current State

最終更新: 2026-09-22。v1.0の完成宣言ではなく、backendの現在の実装範囲。

## Implemented
- FastAPI: Character作成/取得/更新、会話作成/一覧、履歴ページ取得、Memory登録/取得、Provider/model一覧、チャット、要約取得。
- Character Coreの全設定をプロンプトへ注入。履歴はサーバーのSQLiteを原本とする。
- Primary Recall、DraftによるSecondary Recall、最大1回の追加Recall再生成と最大1回の品質修正再生成。
- Guardian不合格時は422。下書きはAPIレスポンスと確定履歴に含めず、評価ログにのみ保持する。
- 空応答、メタ発言、ユーザー行動の決めつけ、一部の反復・禁止語をheuristicで検出。
- 会話単位の抽出型rolling summary。最大12抜粋×160文字、出典message ID・話者・処理済み位置を保存。直近12メッセージを併用する。
- 全文ログを削除しない。古いDBの未要約履歴も小さいバッファで順次処理する。
- プロンプト量のUTF-8 byte上限。固定設定と現在入力は黙って切り捨てず、収まらなければエラーにする。
- turnの原子的保存、revision競合検出、同一会話の並列生成拒否、旧DBへの追加migration、DB接続の明示close。
- Provider streamの正常終了確認、途中切断・error eventの拒否、生成timeoutと出力上限。
- localhost Host/Origin/Fetch Metadata確認、任意のAPIトークン、公開エラーからのProvider詳細除去。
- 51テスト。うち1本はHTTP経由1,000往復、途中再起動、Provider/model切替、出典・DB整合性・プロンプト上限の決定的テスト。

## Explicitly Not Implemented / Unverified
- ReactチャットUI、AIによるUIテスト、Tauri配布、かどか本人による使用テスト。
- 実Ollama / cloud APIへの接続確認と、実モデルで1,000往復した品質・安定性。
- 小型モデルの性能評価、LLMによる意味的な要約・Memory/State自動抽出、vector検索。
- 厳密なモデル別tokenizer、context window検出、出力予約込みのモデル別budget調整。
- 一般的な設定矛盾・関係性変化・幻覚の完全な検出。forbiddenは現状、文字列一致として扱う。
- SSEでの進捗配信、Stop API、Edit/retry、分岐会話、OS credential store、学習データexport。

## Boundaries
抽出型要約は全文の意味を完全に保持しない。新しい重要発言により古い抜粋が外れることがある。
`covered_messages` は処理済み件数であり、その全内容を要約内に保持しているという意味ではない。
全文はSQLiteへ残るが、要約から外れた任意の過去発言を自動検索する仕組みは未実装。
HTTPチャットは検証完了までbufferし、合格した最終応答だけを返す。リアルタイムstreaming UIではない。
会話本文・評価ログはローカルDBに保存する。設定用APIキーを会話本文へ入力しないこと。
既定は単一ユーザー・loopback運用。公開サーバー用の認証/権限設計は含まない。

## Architecture / Validation
設計の原典は `docs/adr/0002-local-webui-desktop-wrapper.md`。
起動・API契約・検証コマンドは `docs/development.md`。実行結果と対象commitはPR/CIで確認する。
