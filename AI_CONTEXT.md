# AI Context

> AI開発時の小さい入口。`ai-context-reducer` の Core 方針をこのrepo向けに適用する。
> 詳細仕様をここへ複製せず、必要な原典へルーティングする。

## Project
- Name: `character_chat_local`
- Purpose: 長期会話でも人格・設定・関係性が崩れにくいキャラクターチャット基盤
- Runtime: Python 3.11+ / FastAPI / SQLite。Desktop UIは将来 Tauri + React を予定。

## Source of Truth
- Product / architecture intent: `README.md`
- Current implementation state: `docs/current-state.md`
- Change routing: `docs/change-routing.md`
- Tasks / acceptance: GitHub Issues
- Executable truth: `src/` and `tests/`

## Read First
1. Current task / Issue
2. `docs/current-state.md`
3. `docs/change-routing.md` の該当行
4. target source -> matching tests
5. 必要な場合だけ `README.md` の関連節

## Ignore Normally
- unrelated Issues / history
- generated files / caches / local DB
- 成功ログ全文
- UI設計（UI taskでない限り）

## Current Task Rules
- Goal / Required / Acceptance が揃ったら追加探索を止める。
- Search first, read second。
- unrelated refactor を混ぜない。
- 要約と原典が衝突したら source / tests / current Issue を優先する。
- 変更後は最小のtargeted validationを先に実行し、shared contract変更時だけ範囲を広げる。

## Important Constraints
- Character Core / Canon と動的Memory・Stateを混同しない。
- 明示事実と推測Memoryを同一扱いしない。
- Provider固有仕様を会話・記憶エンジンへ漏らさない。
- SecretをDB、ログ、export対象へ平文保存しない。
- Secondary Recall / Guardian は無限再生成を起こさない。

## Validation
- `python -m pytest -q`
- `ruff check .`
- Provider実APIはcredentialがある場合のみsmoke。未実施ならUnverifiedとして報告する。

## Context Priority
- P0: current Issue / acceptance / invariant
- P1: target source / tests
- P2: direct dependencies
- P3: README / design docs
- P4: history / unrelated Issues

## Upstream Method
導入方針の参照元: https://github.com/tomiya7688/ai-context-reducer

このrepoは小規模なので、現時点では Core + Current State + Change Routing + targeted validation のみ採用する。Source Structure Index、巨大なContext Pack、階層AIガイドはまだ導入しない。
