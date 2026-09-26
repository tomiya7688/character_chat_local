# Current State

対象: `feat/input-analysis-context-budget`。v1.0の完成宣言ではなく、backendと初期WebUIの実装範囲。

## Implemented
- React / Vite / TypeScript strictのWebUI。キャラクター定義JSONの読込/編集、モデル選択/直接指定、会話開始/再開、品質合格後の表示、Markdown/code、出典付き要約の確認。
- 長期履歴は最新100メッセージから前後に移動する。DB側でwindowを制限し、他会話が挟まるglobal rowidにも対応。
- 初回draftを未確定previewとして逐次表示し、検証/Secondary Recall/Repairの状態を表示する。Final確定時に履歴へ置換する。Stopはprovider taskをcancelし、停止turnを確定履歴へ保存しない。
- Regenerate / Edit & Retry は元会話を変更せず、新しいconversation branchを作る。prefixだけを複製し、Final成功時にbranchを公開する。失敗/Stop時はpending branchを破棄する。
- branchのコピー済みmessageは `origin_message_id`、新しいassistantは `generation_id` を保持する。置換対象generationは成功時だけ `superseded` へ遷移する。
- 品質不合格時は入力を保持。通信結果が不明な場合は自動再送せず、履歴再取得を要求する。IME変換中の誤送信と重複submitを抑止。
- APIトークンはタブのメモリのみ。静的シェルは認証前に読めるが、APIは保護し、Host/Origin確認を維持する。
- build済みWebUIをFastAPI `/ui/` とwheelから配信。外部画像の自動読込・raw HTMLは無効。
- Playwrightの実ブラウザテストをCIへ追加（実API/SQLite + 模擬Provider）。desktop/mobileのスクリーンショットをartifactへ出力。
- FastAPI: Character作成/取得/更新、会話作成/一覧、履歴ページ取得、Memory登録/取得、Provider/model一覧、チャット、要約取得。
- Character Coreの全設定をプロンプトへ注入。履歴はサーバーのSQLiteを原本とする。
- 1ターンを Input Analysis -> Primary Recall -> Context Build -> Draft Generation -> Lightweight Check -> mode別inspect -> Finalize -> post-final hooks -> Evaluation Log の明示stepとして実行し、Turn Traceに結果を保持する。
- Input AnalysisはLLMなしのheuristic-v2で topic / entity / person / place / emotion / intent / time reference / explicit memory requestを構造化し、Turn Traceへ保存する。
- Context Buildは Runtime rules -> Character Core -> Critical Lore -> Relationship State -> Current State -> Relevant Memories -> Recent Conversation -> User Message の順序をコードで固定する。
- MemoryはContext内で FACT / INFERRED / STATE / RELATIONSHIP にラベル分けする。conversation extractは CONVERSATION として分離し、確定FACTへ昇格しない。
- generic推定token上限（既定8,000）とUTF-8 byte上限（既定24,000）の両方を満たす。optional sectionは Relationship 20% / State 15% / Relevant Memory 30% / Recent Conversation 35% を基準に未使用budgetを後段へ繰り越す。
- 固定Character Core / Character Lore / 固定Relationship / 現在入力は黙って切り捨てず、収まらない場合はContextBudgetError。optional memory/historyはwhole record/message group単位で除外する。
- Context Debugはsectionごとのbudget、used tokens、selected/dropped件数、labelと最終token/byte使用量を保持し、Turn Traceのcontext_build stepから確認できる。
- Quality modeは Conversation > Character > Global の順でoverrideする。Global既定は Balanced。
- FastはPrimary Recall + 1回生成 + Lightweight Checkのみ。Balancedはinspect signal時だけDraft Analysis / Secondary Recall / Guardianを実行。Strictは常時Draft Analysis / Secondary Recall / Guardianを実行し、最後にFinal Guardianを再実行する。
- Secondary Recallによる再生成は最大1回、品質修正も最大1回。Fastは追加生成を行わないため1回で終了する。
- Lightweight CheckはLLMなしでempty/length/meta leak/user control/禁止語/exact・near repetitionを検査し、未Recall Memory trigger/entityや強いrelationship/memory変化語をinspect signal化する。
- buffered chatの品質不合格時は422。stream chatでは初回draftのみ未確定previewとして配信可能だが、確定履歴・Memory/State更新には使わない。
- 会話単位の抽出型rolling summary。最大12抜粋×160文字、出典message ID・話者・処理済み位置を保存。直近12メッセージを併用する。
- 全文ログを削除しない。古いDBの未要約履歴も小さいバッファで順次処理する。
- プロンプト量のUTF-8 byte上限。固定設定と現在入力は黙って切り捨てず、収まらなければエラーにする。
- turnの原子的保存、revision競合検出、同一会話の並列生成拒否、generation runの generating/completed/stopped/failed 状態記録、再起動時の孤立run回収、旧DBへの追加migration、DB接続の明示close。
- Provider streamの正常終了確認、途中切断・error eventの拒否、生成timeoutと出力上限。
- localhost Host/Origin/Fetch Metadata確認、任意のAPIトークン、公開エラーからのProvider詳細除去。
- Pythonの回帰テスト。うち1本はHTTP経由1,000往復、途中再起動、Provider/model切替、出典・DB整合性・プロンプト上限の決定的テスト。

## Explicitly Not Implemented / Unverified
- Tauri配布、かどか本人による使用テスト。
- 実Ollama / cloud APIへの接続確認と、実モデルで1,000往復した品質・安定性。
- 小型モデルの実品質評価、LLMによる意味的な要約・Memory/State自動抽出、vector検索。
- #97 Knowledge Extraction と #98 State/Relationship candidate commit の実処理。orchestrator上のpost-final stepは現時点では明示的な skipped hook。
- 厳密なモデル別tokenizer、context window自動検出、出力予約込みのモデル別budget調整。現在の8,000 tokenはprovider-neutralな推定値。
- 一般的な設定矛盾・関係性変化・幻覚の完全な検出。forbiddenは現状、文字列一致として扱う。
- SSEは未採用（現状はPOST + NDJSON stream）。OS credential store、学習データexportは未実装。

## Boundaries
抽出型要約は全文の意味を完全に保持しない。新しい重要発言により古い抜粋が外れることがある。
`covered_messages` は処理済み件数であり、その全内容を要約内に保持しているという意味ではない。
全文はSQLiteへ残るが、要約から外れた任意の過去発言を自動検索する仕組みは未実装。
Input Analysisは形態素解析/NERモデルではなく軽量heuristicであり、固有名詞・意図・感情抽出の完全性を保証しない。
従来の `POST /chat` は検証完了までbufferする。WebUIは `POST /chat/stream` の初回draftを未確定previewとして表示するが、Finalだけを保存済み会話として扱う。
Regenerate / Edit & Retry は会話履歴を破壊的に巻き戻さずbranchを作る。branch作成時はprefixを複製するため、branch数に応じてSQLite上の履歴容量は増える。
この機能追加前の既存assistant messageには `generation_id` がないため、branch自体は作れるが過去generationを遡って `superseded` に結び付けることはできない。
会話本文・評価ログはローカルDBに保存する。設定用APIキーを会話本文へ入力しないこと。
既定は単一ユーザー・loopback運用。公開サーバー用の認証/権限設計は含まない。

## Architecture / Validation
設計の原典は `docs/adr/0002-local-webui-desktop-wrapper.md`。
起動・API契約・検証コマンドは `docs/development.md`。実行結果と対象commitはPR/CIで確認する。

## WebUI limitations
一覧はCharacter/Conversationとも最大500件。履歴そのものは100件単位で遡れる。
Character Coreの独自JSON形式のみ対応（外部character-card形式の互換読込ではない）。
入力中の下書きは画面再読込や会話切替では失われる。確定履歴だけがDBへ保存される。
ブラウザE2Eの合格を、実LLMの出力品質や人間による使用承認として扱わない。
Fast/Balanced/Strictの相対的な品質・速度差は決定的Providerでは評価できない。実モデル評価は別途必要。
