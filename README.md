# character_chat_local

ローカルLLMを中心に、複数のLLMプロバイダーを切り替えて利用できる**キャラクターチャット基盤**を作るプロジェクトです。

単に長い会話履歴をモデルへ渡すのではなく、キャラクター設定・関係性・出来事・現在状態を構造化して保持し、生成前後に必要な情報を思い出させることで、長期会話でも人格や設定が崩れにくい仕組みを目指します。

> Status: **v0.1 proposal / initial design**
>
> このREADMEは初期案です。実装を進めながら細部の仕様・技術選定は変更します。

## Goals

- キャラクター設定を長期会話でも維持する
- 過去の出来事やユーザーとの関係性を忘れにくくする
- LLMの出力を分析し、必要な設定・記憶を追加でRecallする
- キャラ崩壊、設定矛盾、メタ発言、不自然な反復などを検出・補正する
- Ollamaを基本バックエンドとして、ローカルモデルを自由に選択できるようにする
- OpenAI / Gemini / xAI (Grok) などのAPIモデルも同じ会話基盤から利用可能にする
- モデルとキャラクター定義を分離し、同じキャラクターを異なるLLMで動かせるようにする
- 将来的なLoRA / preference tuning / DPO等に利用できる評価データを蓄積する

## Design Principles

### Local-first

Ollamaを主要な実行環境として扱い、可能な処理はローカルで完結できる構成を優先します。

### Provider-agnostic

アプリケーション側は特定LLMのAPI仕様に依存せず、共通Provider interfaceを通してモデルを利用します。

想定Provider:

- Ollama
- OpenAI API
- Google Gemini API
- xAI API
- 将来: OpenRouter / LM Studio / vLLM / llama.cpp server など

### Character-first

一般的なAIチャットではなく、**人格・設定・関係性・継続性**を優先したキャラクターチャットとして設計します。

## High-level Architecture

```text
User
  ↓
Input Analyzer
  ↓
Primary Recall
  ├─ Character Core
  ├─ Canon / Lore
  ├─ Relationship Memory
  ├─ Episodic Memory
  └─ Current State
  ↓
Generation Engine
  ├─ Ollama
  ├─ OpenAI
  ├─ Gemini
  └─ xAI
  ↓
Draft Response
  ↓
Output Analyzer
  ↓
Secondary Recall
  ↓
Guardian / Consistency Check
  ├─ Character consistency
  ├─ Lore consistency
  ├─ Memory consistency
  ├─ Repetition
  ├─ Meta leakage
  └─ User-control detection
  ↓
Repair / Regenerate (if needed)
  ↓
Final Response
  ↓
Memory / State Update
```

## Core Components

### Character Engine

キャラクターの固定的な人格・設定を管理します。

例:

- 名前
- 一人称 / 二人称
- 口調
- 性格
- 価値観
- 好き嫌い
- 生い立ち
- 世界設定
- 禁止事項
- ユーザーとの基本関係

重要なCanon情報は会話要約だけに依存せず、構造化データとして保持します。

### Memory Engine

会話から長期的に有用な情報を抽出・保存します。

初期案では以下を分離します。

- **Canon Memory**: 変更してはいけない設定
- **Relationship Memory**: ユーザーとの関係や約束
- **Episodic Memory**: 会話内で実際に起きた出来事
- **User Facts**: ユーザーが明示した情報
- **Inferred Facts**: 会話から推測された情報（事実と区別して信頼度を持つ）
- **Current State**: 場所、感情、状況、直前の出来事など

Memoryには、本文だけでなくRecall用のメタデータを持たせる予定です。

```json
{
  "type": "character_memory",
  "content": "雨の日には昔の事故を思い出す",
  "importance": 0.92,
  "confidence": 1.0,
  "triggers": ["雨", "雷雨", "傘", "事故"],
  "entities": ["雨", "事故"],
  "emotions": ["anxiety", "sadness"],
  "recall_mode": "emotional"
}
```

### Recall Engine

このプロジェクトの重要機能です。

通常のRAGのようにユーザー入力だけで一度検索して終わるのではなく、**LLMが生成したDraftも分析して追加Recall**します。

```text
User Input
  ↓
Primary Recall
  ↓
Draft Generation
  ↓
Draft Analysis
  ↓
Secondary Recall
  ↓
不足設定 / 関連記憶 / 矛盾を検出
  ↓
Repair or Regenerate
```

これにより、最初の検索では見つけにくかった設定も、モデルが「何を話そうとしているか」を手掛かりに再検索できます。

Recallは単純なEmbedding similarityだけではなく、将来的に以下を組み合わせます。

- semantic similarity
- keyword / trigger match
- entity match
- emotional relevance
- importance
- relationship relevance
- recency
- activation threshold
- cooldown

### Recall Modes

記憶を思い出しても、必ずその内容をセリフとして説明するわけではありません。

想定モード:

- `explicit`: 必要なら内容を直接言及できる
- `implicit`: 会話の前提として利用する
- `behavioral`: 行動・言葉選びに反映する
- `emotional`: 感情反応に反映する
- `internal_only`: 内部前提としてのみ利用し、直接明かさない

### State Engine

固定人格と現在状態を分離します。

```text
Character
  ├─ Immutable Core
  ├─ Long-term Memory
  ├─ Relationship State
  └─ Dynamic State
```

Dynamic Stateの例:

- current emotion
- current location
- current relationship
- trust / affection
- current concern
- unresolved event

### Generation Engine

Providerの違いを吸収し、同じ会話・キャラクターを異なるモデルで実行できるようにします。

概念的には以下のようなinterfaceを想定しています。

```ts
interface AIProvider {
  id: string;
  listModels(): Promise<ModelInfo[]>;
  chat(request: ChatRequest): AsyncIterable<ChatEvent>;
  abort?(requestId: string): Promise<void>;
}
```

実際のProvider domain logicはPython backend側をsource of truthとし、TypeScript側にはUI向けの型・clientを提供します。

Ollamaは主要Providerとして、将来的に以下も扱います。

- server endpoint
- installed model discovery
- model pull / delete
- context length
- temperature等の生成設定
- remote Ollama server

### Guardian Engine

生成された回答をそのまま表示せず、必要に応じて品質チェック・補正します。

検出対象の例:

- Character Break: キャラ崩壊
- Lore Violation: 世界観・設定矛盾
- Memory Violation: 過去の出来事との矛盾
- User Control: ユーザーの行動やセリフを勝手に確定する
- Repetition: 同じ表現や反応の過剰反復
- Over-recall: 関係ない設定を不自然に持ち出す
- Under-recall: 必要な設定を無視する
- Meta Leak: 「AIとして」等の不要なメタ発言
- Relationship Jump: 根拠なく関係性が急変する
- Emotion Jump: 理由なく感情が急変する
- Hallucinated Event: 存在しない過去を作る
- Formatting Break: 指定された表現形式を破る

必要ならDraftをRepairまたはRegenerateしてから表示します。

## Multi-model Roles

1つのモデルですべてを処理する必要はありません。

例:

```text
Main conversation      -> large local model / cloud model
Memory extraction      -> small local model
Output analysis        -> small local model
Consistency validation -> small local model
```

これにより、クラウドAPI利用時でも補助処理をOllamaへ逃がし、コストやレイテンシを調整できます。

## Proposed Data Model

初期候補:

```text
characters
character_facts
world_facts
conversations
messages
relationships
memories
memory_sources
character_states
provider_configs
model_configs
response_evaluations
```

詳細なschemaは実装Issueで決定します。

## v0.1 Language / Runtime Decision

主開発言語は **Python + TypeScript** とします。

- **Python 3.11+**: FastAPI local backend、Provider、Character、Memory、Recall、State、Guardian、Storage
- **TypeScript (strict)**: React frontend、Chat UI、Character editor、Settings、Debug UI
- **Rust**: Tauri shell、Python sidecar lifecycle、native OS integrationに限定
- **SQL**: SQLite schema / migration

詳細は [`docs/adr/0001-development-languages.md`](docs/adr/0001-development-languages.md) を参照してください。

### Desktop / UI

- Tauri 2
- React
- TypeScript
- Vite
- Tailwind CSS
- shadcn/ui

### Local Backend

- Python 3.11+
- FastAPI
- Pydantic
- async HTTP client
- Tauri sidecarとしてdesktop appへ同梱する方向

### Storage

- SQLite
- SQL migrations
- 必要に応じてvector search layerを追加

### LLM

- Ollama
- OpenAI API
- Gemini API
- xAI API

### Language boundary

```text
React / TypeScript
       │
       │ HTTP / streaming
       ▼
Python / FastAPI
       │
       ├── SQLite
       └── Ollama / Cloud LLM APIs

Rust / Tauri
       └── window / packaging / sidecar / native integration
```

Character / Memory / Recall / Guardian / Provider等のdomain logicはPython側をsource of truthとし、RustやReact componentへ二重実装しません。

## v0.1 Scope

最初の実用版では、機能を以下に絞る予定です。

- キャラクター作成 / 編集
- Ollama接続
- モデル一覧・選択
- 基本チャット
- ストリーミング生成
- 会話履歴保存
- Character Core注入
- 構造化Memory保存
- Primary Recall
- Draft Output Analysis
- Secondary Recall
- 基本的なGuardian / Repair loop
- OpenAI / Gemini / xAI Provider追加
- Provider credential設定

## Future: Evaluation and Fine-tuning

初期段階ではLoRA等に依存せず、まずシステム側で品質を上げます。

利用中に以下を保存できるようにします。

```text
original response
  ↓
validator result
  ↓
user feedback
  ↓
repaired / preferred response
```

このデータを将来的に、キャラクターチャット向けのLoRA、preference tuning、DPO等に利用できる形へ整備します。

Pythonをruntime coreにも採用することで、評価・データ加工・学習実験との知識共有をしやすくします。

## Non-goals for the first version

v0.1では以下を優先しません。

- 大規模なモデル学習基盤
- クラウド同期
- SNS的なキャラクター共有機能
- 高度なマルチユーザー機能
- 完全な自律Agent化

まずは**長期間会話しても設定・人格・関係性が壊れにくいキャラクターチャット**を成立させることを優先します。

## Development

現在は設計初期段階です。実装タスクや仕様検討はGitHub Issuesで管理します。

## License

TBD
