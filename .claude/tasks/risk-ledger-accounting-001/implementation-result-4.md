Status: PASS

## Summary

承認済みタスクと C1-C8、D1-D3、E1-E4 の修正を完了しました。

- Freshness は全 venue I/O 後の clock で評価
- Checkpoint は記録済み ledger binding のみを保存
- 同一 risk group の二重起動を advisory lock で拒否
- `complete` / `authoritative` は厳密な `bool` として検証
- Ledger、venue authority、residual strategy、state schema v2、recovery 動作を維持

## Files changed

- [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:986)
- [ledger.py](/Users/ohayotaro/claude-finance/src/risk/ledger.py:125)
- [test_aggregator.py](/Users/ohayotaro/claude-finance/tests/test_risk/test_aggregator.py:2447)
- [test_ledger.py](/Users/ohayotaro/claude-finance/tests/test_risk/test_ledger.py:306)
- [risk_groups.toml](/Users/ohayotaro/claude-finance/config/risk_groups.toml:1)
- [DESIGN.md](/Users/ohayotaro/claude-finance/.claude/docs/DESIGN.md:44)
- [test-evidence.md](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-001/test-evidence.md)
- [implementation-result.md](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-001/implementation-result.md)
- [review.md](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-001/review.md)

承認済み [plan.md](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-001/plan.md) は維持しています。既存の dirty `state.json` は変更していません。

## Material design decisions

- `now_utc` は cycle-start と UTC day attribution 専用です。Observation freshness には使用しません。
- Checkpoint save は ledger binding の不一致時に CRITICAL を記録して保存を拒否します。
- `run_forever` の全期間で risk-group ledger directory の `flock` を保持します。
- Truthy な文字列や整数を authority/completeness として受理しません。
- Empty ledger の generation-zero bootstrap のみ、未照合状態として明示的に保存可能です。

## Exact validation commands and results

- `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run --extra dev pytest tests/test_risk/ -v`
  - `116 passed in 0.52s`
- `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run --extra dev pytest -m "not integration and not slow"`
  - `285 passed in 6.98s`
- `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run --extra dev ruff check src/ tests/ .claude/hooks/ .claude/scripts/`
  - `All checks passed!`
- `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run --extra dev mypy src/ .claude/scripts/`
  - `Success: no issues found in 14 source files`
- `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run python -m src.orchestrator.registry audit`
  - `audit: ok (0 strategies, 0 accounts)`
- `git diff --check`
  - Exit code 0

Fast-suite count: `215 -> 258 -> 285 passed`。全42件の新規 logical test、failing-first evidence、legacy replacements は [test-evidence.md](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-001/test-evidence.md) に記録済みです。

## Acceptance-criteria mapping

| AC | Result | Evidence |
|---|---|---|
| AC1 | PASS | Net-cost/funding、idempotent replay、identity-conflict ledger tests |
| AC2 | PASS | Venue-zero、position omission、log telemetry isolation tests |
| AC3 | PASS | Disabled/deprecated residual、failed/incomplete/non-boolean observation tests |
| AC4 | PASS | Rotation、truncation、restart、late fill、UTC attribution、checkpoint binding、single-writer tests |
| AC5 | PASS | Schema v2 metadata、consumer age recomputation、post-fetch clock、independent observation ages |
| AC6 | PASS | Example config、non-finite値、currency、slug、path validation |
| AC7 | PASS | 全必須 offline validation と evidence requirements が成功 |
| AC8 | PASS | ADR-005 に authority、migration、locking、ADR-004 exception を記録 |

## Residual risks, debt, or blockers

- 実 venue adapter がないため、venue固有 cursor、timestamp、normalized PnL は未検証です。
- Exposure は引き続き `size * entry_price` です。Mark/current notional は後続課題です。
- Writer lock は同一ホスト内のみ有効です。
- Ledger compaction と multi-currency conversion は対象外です。
- 実装上の blocker はありません。