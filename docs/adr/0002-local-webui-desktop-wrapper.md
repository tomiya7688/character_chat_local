# ADR-0002: Local WebUI + Desktop Wrapper Architecture

- Status: Accepted
- Date: 2026-09-15
- Scope: v0.1 runtime / UI delivery architecture

## Decision

`character_chat_local` は、**ローカルWebUIをアプリケーション本体とし、Tauriをデスクトップ配布・OS統合用のラッパーとして利用する**。

Python/FastAPI backend と React/TypeScript frontend は、TauriなしでもローカルWebアプリとして起動できる構成にする。

```text
Browser or Tauri WebView
        │
        │ HTTP / streaming
        ▼
Python / FastAPI
        │
        ├─ Character Engine
        ├─ Memory Engine
        ├─ Recall Engine
        ├─ State Engine
        ├─ Guardian Engine
        ├─ Provider Layer
        ├─ SQLite
        └─ Ollama / OpenAI / Gemini / xAI

Tauri
  ├─ desktop window
  ├─ local backend lifecycle
  ├─ native OS integration
  ├─ credential integration
  └─ packaging / installer
```

## Runtime Modes

### Local WebUI mode

開発・デバッグ・サーバー用途では、FastAPIとfrontendを直接起動し、通常のブラウザから利用できる。

想定例:

```text
character-chat-local serve
        ↓
http://127.0.0.1:<port>
```

デフォルトではloopbackのみへbindし、LAN公開は明示的な設定なしでは有効化しない。

### Desktop mode

配布版ではTauriを起点とする。

1. TauriがPython backendをsidecarとして起動
2. health check完了を待つ
3. Tauri WebViewで同じfrontendを表示
4. 終了時にbackendをgraceful shutdownする

Desktop版専用のdomain logicは原則作らない。

## Why this architecture

- WebUI単体で開発・デバッグできる
- frontendとbackendの責務境界が明確になる
- Tauriへの依存をUI配布層へ限定できる
- 将来Docker / headless / LAN access等へ拡張しやすい
- PythonのAI domain coreをそのまま再利用できる
- Desktop版とWebUI版でCharacter / Memory / Recall / Guardianの挙動を共通化できる

## API boundary

FrontendはFastAPIの公開APIのみを利用する。

- REST: CRUD / settings / character / conversation / memory等
- streaming: chat generation
- OpenAPI schemaをTypeScript client/types生成のsourceとして利用する方向

Tauri IPCは、OS integrationなどDesktop固有機能に限定する。

例:

- secure credential store
- native file picker
- notifications
- window control
- sidecar lifecycle

LLM会話そのものをTauri IPCへ依存させない。

## Security defaults

- backendのdefault bindは `127.0.0.1`
- LAN公開はopt-in
- cloud provider API keyをfrontendへ常駐させない
- Desktop版ではcredentialをOS credential storeからbackendへ安全に受け渡す方式を検討する
- localhost APIでも、必要に応じてsession token / origin check等を導入する

## Consequences

### Positive

- Tauriなしでもアプリが成立する
- browser devtoolsを使ったUI開発が容易
- APIのテスト・自動化が容易
- Desktop以外の利用形態へ拡張しやすい
- backend/frontendを独立してテストできる

### Trade-offs

- localhost backendのport/lifecycle管理が必要
- Desktop版ではsidecar packagingが必要
- frontend-backend間にAPI serializationコストがある
- localhost APIのアクセス制御を考慮する必要がある

## v0.1 rules

1. Local WebUIを第一級の実行モードとして維持する。
2. Tauriがなくても主要機能を利用可能にする。
3. Tauri固有機能をdomain layerへ混入させない。
4. backendはデフォルトでloopbackのみにbindする。
5. DesktopとWebUIで同じFastAPI APIと同じReact frontendを使う。
6. Tauri IPCはnative integration用途に限定する。
7. LAN / remote accessはv0.1では必須要件にしない。
