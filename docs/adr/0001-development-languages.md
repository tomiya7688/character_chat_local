# ADR-0001: Development Languages

- Status: Accepted
- Date: 2026-09-14
- Scope: v0.1 application architecture

## Context

`character_chat_local` は Desktop-first / Local-first / Provider-agnostic なキャラクターチャットアプリを目指す。

主な要件は以下。

- Tauriベースのデスクトップアプリ
- Ollamaを主要LLMバックエンドとして利用
- OpenAI / Gemini / xAI等のクラウドProviderにも対応
- Character / Memory / Recall / Guardianをローカルで管理
- SQLiteによる永続化
- ストリーミング応答
- Windows / macOS / Linuxへの配布を想定
- 将来的に評価データ作成、LoRA / DPO等の実験を行う

`feat/initial-core-context-reducer` ではすでに Python / FastAPI ベースで Provider、Recall、Guardian、Storage 等の初期実装が進んでいる。これらは今後も実験・調整の頻度が高い領域であり、PythonのLLM/MLエコシステムとの親和性も高い。

一方、デスクトップUIはTauri + Reactを想定しているため、UIにはTypeScriptを利用する。RustはTauriのnative shellおよびOS統合に限定し、v0.1ではdomain logicをRustへ分散させない。

## Decision

### Primary languages: Python + TypeScript

v0.1の主開発言語は以下の2つとする。

- **Python**: application core / local backend / LLM orchestration
- **TypeScript**: frontend / desktop UI

加えて、Tauriが必要とする最小限の **Rust** と、SQLite migration用の **SQL** を利用する。

## Python

Pythonをアプリケーションコアに使用する。

### Version policy

- Python 3.11+
- 型注釈を必須とする方向で運用
- Pydantic modelをAPI/domain境界のschemaとして利用

### Responsibilities

- FastAPI local service
- LLM Provider abstraction
- Ollama / OpenAI / Gemini / xAIとの通信
- streaming response orchestration
- Character Engine
- Memory Engine
- Recall Engine
- State Engine
- Guardian / Validator / Repair loop
- SQLite access
- evaluation logging
- dataset export
- 将来のembedding / reranking / ML experimentation

### Why Python

- Provider / Recall / Guardian等の初期実装がすでに存在する
- Character tuningやRecall scoringは試行錯誤が多く、変更速度を重視したい
- Pydantic / FastAPIによりschemaとAPIを明確に保ちやすい
- LLM / embedding / reranking / evaluation / fine-tuning周辺のライブラリへ移行しやすい
- 将来のLoRA / DPO / benchmark toolingと同じ言語を利用できる

## TypeScript

TypeScriptをFrontendに使用する。

### Policy

- JavaScriptではなくTypeScriptを使用
- `strict` modeを前提とする
- React + Viteを基本構成とする

### Responsibilities

- Chat UI
- Character editor
- Conversation list
- Model / Provider selector
- Settings UI
- Memory / Recall / Guardian debug UI
- frontend state management
- FastAPI client
- Tauri integration layer

### Why TypeScript

- React / Vite / Tauri frontendとの親和性が高い
- Character / Memory / Validator等の複雑なUI stateを型安全に扱える
- Python側schemaから生成したAPI typesを利用しやすい
- UIのdomain logic混入を型境界で抑えやすい

## Rust

Rustは **主開発言語にはしない**。

Tauri shellと、Python/TypeScriptだけでは扱いづらいnative機能に限定する。

### Responsibilities

- Tauri application entrypoint
- Python sidecar lifecycle
- process start / stop / health supervision
- OS credential storeへのbridge（必要な場合）
- filesystem / native dialog等のOS integration
- application packaging / updater integration

### Rule

Character / Memory / Recall / Guardian / Provider等のdomain logicは、性能上の明確な理由がない限りRustへ実装しない。

Rust実装が必要になった場合は、Pythonとの責務境界を明示する。

## SQL

SQLite schema / migrationはSQLファイルとして管理する。

SQLは主開発言語ではなく永続化定義として扱う。

## Runtime architecture

```text
┌────────────────────────────────────────────┐
│ React / TypeScript                         │
│                                            │
│ Chat / Character / Settings / Debug UI     │
└────────────────────┬───────────────────────┘
                     │ HTTP / streaming
                     ▼
┌────────────────────────────────────────────┐
│ Python / FastAPI local service             │
│                                            │
│ Provider / Character / Memory / Recall     │
│ State / Guardian / Storage / Evaluation    │
└───────────────┬───────────────────┬────────┘
                │                   │
                ▼                   ▼
             SQLite             LLM APIs
                                ├─ Ollama
                                ├─ OpenAI
                                ├─ Gemini
                                └─ xAI

┌────────────────────────────────────────────┐
│ Rust / Tauri shell                         │
│                                            │
│ Window / packaging / sidecar / OS bridge   │
└────────────────────────────────────────────┘
```

## Tauri and Python sidecar

Desktop配布時はPython serviceをsidecarとして同梱する方向とする。

Tauriはexternal binary / sidecarの同梱と起動をサポートしており、Python CLIやAPI serverをfreezeして同梱する構成を取れる。

v0.1では以下を検討する。

- PyInstaller等でPython serviceをplatform binary化
- Tauriからsidecarを起動
- localhostの固定/動的portまたはstdio/IPCの選定
- health check
- graceful shutdown
- crash recovery
- log routing

sidecar配布が実際に重大な問題となった場合のみ、Rust core化を再検討する。

## Communication boundary

Frontendとbackendの責務を混ぜない。

### TypeScript -> Python

- HTTP request/response
- streaming response
- schema化されたJSON

### Rust -> Python

- process lifecycle
- startup configuration
- optional native secret access

### Forbidden by default

- UIからProvider APIへ直接request
- API keyをlocalStorageへ保存
- Character/Recall/GuardianのロジックをReact componentへ実装
- 同じdomain logicをPythonとRustへ二重実装

## Type sharing

PythonとTypeScript間の型ずれを防ぐ。

候補:

1. FastAPI OpenAPI schemaからTypeScript client/typeを生成
2. Pydantic modelをbackend側のsource of truthとする
3. API DTOと内部domain modelを必要に応じて分離する

v0.1では **OpenAPI -> TypeScript生成** を第一候補とする。

## Initial language layout

```text
character_chat_local/
├─ src/
│  └─ character_chat_local/     # Python core/backend
├─ tests/                       # Python tests
├─ frontend/                    # React / TypeScript
├─ src-tauri/                   # minimal Rust / Tauri shell
├─ migrations/                  # SQL
├─ tools/                       # Python evaluation/training tools
└─ docs/
   └─ adr/
```

フロントエンド追加時に既存Pythonの `src/` と名前が衝突しないよう、TypeScript側は `frontend/` に置く。

## Consequences

### Positive

- 既存Python実装を活かせる
- Recall / Guardian / Memoryの実験速度を維持できる
- ML/LLM ecosystemを直接利用できる
- UIはTypeScriptで型安全に作れる
- Rustを必要最小限にでき、3言語へdomain logicが分散するのを防げる
- 将来の評価・fine-tuningとruntime coreの知識を共有できる

### Trade-offs

- Desktop配布時にPython sidecar packagingが必要
- frontend/backend間の通信層が必要
- platformごとのsidecar build/署名を考慮する必要がある
- Rust単一binary構成よりinstaller sizeは大きくなる

これらはv0.1では、実装速度・LLM機能の実験容易性を優先して受け入れる。

## Rules

1. Domain coreはPythonをsource of truthとする。
2. FrontendはTypeScript strictで実装する。
3. RustはTauri shell/native integrationに限定する。
4. Provider API keyをFrontendへ永続化しない。
5. Python API schemaをTypeScript側へ自動生成できる構成を目指す。
6. SQL migrationをversion controlする。
7. 性能問題は計測してからRust移植を検討する。
8. Rustへ移植する場合もPython版と二重保守しない。

## Revisit conditions

以下の場合、このADRを再検討する。

- Python sidecarの配布・起動安定性がプロダクト品質を妨げる
- Recall/Guardian処理がCPU性能上の明確なボトルネックになる
- Python runtimeのメモリ使用量が許容できない
- Mobile対応等によりFastAPI sidecar方式が成立しなくなる
- Tauri/Rust側へ統合することで明確な運用上の利益が得られる

## References

- Tauri architecture: https://v2.tauri.app/concept/architecture/
- Tauri sidecars: https://v2.tauri.app/develop/sidecar/
