# ADR-0003: Continuous Integration Policy

- Status: Accepted
- Date: 2026-09-15
- Scope: v0.1 development workflow

## Decision

GitHub Actions をCI基盤として使用する。

Local WebUI + Tauri wrapper構成に合わせ、CIを以下の独立コンポーネントに分ける。

1. Python backend
2. React / TypeScript WebUI
3. Rust / Tauri wrapper

まだ存在しないコンポーネントは自動的にskipし、追加された時点から同じworkflowで検証を開始する。

## Triggers

CIは以下で実行する。

- `push`
- `pull_request`
- manual `workflow_dispatch`

同一branchで古いrunが残っている場合は `concurrency` によりcancelし、最新commitを優先する。

## Permissions

CI workflowのGitHub tokenは原則 `contents: read` のみに制限する。

CIからrepository内容を書き換えたり、release/publishしたりしない。配布・releaseは将来別workflowへ分離する。

## Backend CI

`pyproject.toml` が存在する場合に実行する。

Python support baselineに合わせ、v0.1では以下を検証する。

- Python 3.11
- Python 3.12

Checks:

```text
pip install -e '.[dev]'
ruff check .
ruff format --check .
pytest -q
```

Providerの実API keyはCIへ渡さない。unit testは外部LLM APIに依存せず、mock/fake providerで実行可能にする。

## Frontend CI

`frontend/package.json` が存在する場合に実行する。

Baseline:

- Node.js 22
- lockfile必須

対応lockfile:

- `package-lock.json`
- `pnpm-lock.yaml`
- `yarn.lock`

Checks:

- dependency install with frozen lockfile semantics
- `lint` script（存在する場合）
- `typecheck` script（存在する場合）
- `test` script（存在する場合）
- `build` script（必須）

WebUIはTauriなしでもbuild可能であることをCIで維持する。

## Tauri CI

`src-tauri/Cargo.toml` が存在する場合に実行する。

Checks:

```text
cargo fmt --check
cargo clippy --all-targets --all-features -- -D warnings
cargo test --all-targets --all-features
```

Linux runnerではTauri build/checkに必要なWebKitGTK等のsystem dependenciesを導入する。

TauriのCIがFrontend/Backendのdomain testを代替しないことを原則とする。

## CI Gate

個々のjobとは別に `CI Gate` jobを用意する。

存在するコンポーネントのjobがfailure/cancelledの場合は失敗し、未実装コンポーネントのskipは許容する。

将来branch protectionを設定する際は、変動するmatrix jobではなく `CI Gate` をrequired status checkの第一候補とする。

## Architecture invariants checked by CI

CIは次の構成を維持するための基盤とする。

- Python backendは単独でtest可能
- WebUIはTauriなしでbuild可能
- Tauri wrapperはRust側でlint/test可能
- cloud provider credentialなしで通常testが通る
- domain logicをDesktop固有runtimeへ依存させない

## Future additions

必要になった段階で以下を別job/workflowとして追加する。

- OpenAPI -> TypeScript client生成差分チェック
- SQLite migration test
- backend + frontend integration test
- Playwright E2E
- Python sidecar freeze/build test
- Windows / macOS / Linux Tauri packaging matrix
- release signing / artifact publishing
- dependency/security scanning

Release/CDは通常CIとは分離する。
