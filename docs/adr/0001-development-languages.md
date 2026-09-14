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

Python/FastAPIをアプリ本体のsidecarとして利用する案も検討したが、v0.1では配布・プロセス管理・IPC・runtime同梱の複雑さを増やさないことを優先する。

## Decision

### Application runtime: Rust + TypeScript

アプリ本体は **Rust + TypeScript** の2言語を基本とする。

### Rust

Rustをアプリケーションコアに使用する。

担当範囲:

- Tauri backend / native commands
- LLM Provider abstraction
- Ollama / OpenAI / Gemini / xAIとのHTTP通信
- streaming response orchestration
- Character Engine
- Memory Engine
- Recall Engine
- State Engine
- Guardian / Validator / Repair loop
- SQLite access / migrations execution
- credential / OS integration
- filesystem access
- background tasks / cancellation

原則として、LLM API keyや内部Memory等の機微な情報をFrontendだけで処理しない。

### TypeScript

TypeScriptをFrontendに使用する。

担当範囲:

- React UI
- Character editor
- Chat UI
- Conversation / model selector
- Settings UI
- Memory / Recall / Guardian debug UI
- frontend state management
- Tauri IPC client

JavaScriptではなくTypeScriptを必須とし、`strict` modeを前提とする。

### Python

Pythonは **アプリ本体のruntimeには含めない**。

`tools/` 配下の開発・研究用途に限定する。

用途例:

- evaluation scripts
- conversation log analysis
- dataset cleanup / conversion
- preference pair generation
- benchmark scripts
- LoRA / DPO / fine-tuning experiments
- prototype / offline analysis

Pythonで有効性が確認されたアルゴリズムを本番runtimeへ入れる場合は、原則Rustへ移植する。Python runtimeが必須になる機能が将来登場した場合は、別ADRでsidecar導入を再検討する。

### SQL

DB schema / migrationはSQLファイルとして管理する。

SQLはアプリケーションの主開発言語ではなく、永続化定義として扱う。

## Runtime boundary

```text
┌───────────────────────────────────────┐
│ React / TypeScript                    │
│                                       │
│ UI / editor / chat / debug views      │
└─────────────────┬─────────────────────┘
                  │ Tauri IPC / Channel
                  ▼
┌───────────────────────────────────────┐
│ Rust / Tauri Core                     │
│                                       │
│ Provider / Character / Memory         │
│ Recall / State / Guardian / Storage   │
└──────────────┬───────────────┬────────┘
               │               │
               ▼               ▼
            SQLite         LLM APIs
                           ├─ Ollama
                           ├─ OpenAI
                           ├─ Gemini
                           └─ xAI

Development only:
Python tools -> evaluation / dataset / training
```

## Why not Python/FastAPI for the v0.1 runtime?

PythonはLLM/ML周辺の開発速度に優れる一方、Tauriデスクトップアプリへ常駐sidecarとして組み込むと以下が増える。

- Python runtimeまたはfreeze済みbinaryの配布
- OS/architecture別build
- sidecar lifecycle管理
- Rust/frontendとの追加IPC
- crash / port / process管理
- installer sizeとbuild pipelineの複雑化

v0.1のMemory / Recall / Guardianは、外部LLM APIとSQLiteを中心に構成できるためPython常駐backendを必須としない。

## Why Rust for the application core?

- Tauriのnative側と同じ言語に統一できる
- 別backend processを不要にできる
- async HTTP / streaming / cancellationを一箇所で管理できる
- API keyやDBをWebViewから分離できる
- Windows / macOS / Linux向けに単一構成でbuildしやすい
- SQLiteおよびvector searchをRust側から利用可能

## Why TypeScript for the frontend?

- React/Vite/Tauriとの親和性が高い
- Character / Memory / Validator等の複雑なUI modelで型安全性が重要
- IPC payloadの型を管理しやすい
- JavaScriptへの段階的な型追加ではなく最初からstrictにできる

## Rules

1. 本番runtimeにNode.js serverを追加しない。
2. 本番runtimeにPython sidecarを追加しない。
3. UIからLLM Providerへ直接API key付きrequestを送らない。
4. Provider / Memory / Recall / Guardian等のdomain logicはRust側に置く。
5. TypeScript側はpresentation / interactionを中心とする。
6. Python prototypeが本番機能になる場合はRust移植を基本とする。
7. 例外が必要になった場合はADRを追加する。

## Initial language layout

```text
character_chat_local/
├─ src/                 # TypeScript / React
├─ src-tauri/           # Rust / Tauri application core
├─ migrations/          # SQL
├─ tools/               # Python development/evaluation tools
└─ docs/
   └─ adr/
```

## Consequences

### Positive

- 配布runtimeがシンプルになる
- Tauri/Rustとbackend logicを統合できる
- secret / DB / filesystem境界が明確になる
- TypeScript UIとRust coreの責務分離が明瞭になる
- PythonのML ecosystemも開発用途では自由に使える

### Trade-offs

- Recall/Memoryアルゴリズムの実験はPythonよりRustの方が反復速度が落ちる場合がある
- Rust/TypeScript間の型同期が必要
- 一部ML libraryを直接runtimeで使いたい場合に選択肢が狭くなる

これらは、Pythonをoffline toolとして維持し、必要に応じて型生成や共通schema生成を導入することで緩和する。

## Revisit conditions

以下のいずれかが発生した場合、この決定を再検討する。

- Python専用ML libraryをruntimeで利用することがプロダクト上必須になった
- ローカル推論をOllama以外のPython runtimeで直接ホストする必要が出た
- Rust実装による開発コストがボトルネックになった
- Tauri sidecar導入の利点が配布複雑性を明確に上回った
