Status: PASS

## Summary

承認済みの実装と C1-C8、D1-D3 の修正を完了しました。

- 実現損益は、手数料・commission・funding・borrow cost・明示的 cash event を含む SQLite ledger から算出します。
- 含み損益、exposure、margin、drawdown、position/order 数は venue observation のみを使用します。
- freshness は全 venue I/O 完了後に injectable UTC clock を1回読み取って評価します。
- ledger commit 後の計算失敗は即座に fail-closed とし、古い risk state を新しい ledger generation に紐付ける checkpoint 保存を禁止します。
- State schema v2、checkpoint schema v3、metric provenance、inactive strategy の residual monitoring、log rotation/truncation recovery を実装済みです。
- Network、取引、credential、dependency追加、commit、push、deploy、禁止ファイルの変更はありません。

## Files changed

- [src/risk/ledger.py](/Users/ohayotaro/claude-finance/src/risk/ledger.py:125)
- [src/risk/aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:975)
- [tests/test_risk/test_ledger.py](/Users/ohayotaro/claude-finance/tests/test_risk/test_ledger.py:74)
- [tests/test_risk/test_aggregator.py](/Users/ohayotaro/claude-finance/tests/test_risk/test_aggregator.py:1914)
- [config/risk_groups.toml](/Users/ohayotaro/claude-finance/config/risk_groups.toml:1)
- [.claude/docs/DESIGN.md](/Users/ohayotaro/claude-finance/.claude/docs/DESIGN.md:44)
- [implementation-result.md](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-001/implementation-result.md:1)

既存の dirty な `state.json` と review/runner artifacts は変更していません。

## Material design decisions

- Fill identity は `(account_scope, strategy_id, symbol, order_id, fill_id)`。同一 replay は no-op、内容が異なる同一 identity は fail-closed。
- Ledger row、venue cursor、generation を同一 SQLite transaction で更新。
- Post-commit failure 後は checkpoint を保存せず、再起動時に ledger/checkpoint mismatch を検出。
- Venue timestamp の future skew はデフォルト2秒、設定可能範囲は0–5秒。
- Disabled/deprecated/retired strategy は、complete venue cycle で position/order ともにゼロになるまで risk-visible。
- 単一 account scope・単一 quote currency を強制。通貨換算は adapter normalization 境界へ延期。

## Exact validation commands and results

- `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run --extra dev pytest tests/test_risk/ -v`
  - PASS: `89 passed in 0.43s`
- `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run --extra dev pytest -m "not integration and not slow"`
  - PASS: `258 passed in 6.58s`
- `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run --extra dev ruff check src/ tests/ .claude/hooks/ .claude/scripts/`
  - PASS: `All checks passed!`
- `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run --extra dev mypy src/ .claude/scripts/`
  - PASS: `Success: no issues found in 14 source files`
- `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run python -m src.orchestrator.registry audit`
  - PASS: `audit: ok (0 strategies, 0 accounts)`
- `git diff --check`
  - PASS

Fast-suite countは、task開始前 `215`、C1-C8後 `254`、最終 `258` です。D1-D2の3テストは実装前に `3 failed`、実装後に `3 passed` を確認しました。

## Acceptance-criteria mapping

| AC | Result | Evidence |
|---|---|---|
| AC1 | PASS | Decimal known-value、cost/funding、duplicate/shuffled replay、identity conflict tests |
| AC2 | PASS | venue zero/omission が log telemetry を cap accounting から排除する tests |
| AC3 | PASS | disabled/deprecated residual、incomplete/stale/post-fetch aging tests |
| AC4 | PASS | rotation、truncation、restart、late fill、UTC attribution、ledger/checkpoint mismatch、post-commit failure tests |
| AC5 | PASS | schema v2 metadata、consumer recomputed age、`published_at`、independent observation age tests |
| AC6 | PASS | example config、non-finite、currency、slug、path confinement tests |
| AC7 | PASS | 全必須 test/lint/mypy/audit が offline で成功。37件の新規test名と3件のlegacy replacementを implementation result に記録 |
| AC8 | PASS | ADR-005にaccounting model、migration、crash behavior、ADR-004例外を記録 |

## Residual risks, debt, or blockers

- 実 venue adapter がないため、venue固有のcursor completeness、timestamp、normalized PnLは未検証です。
- Exposureは現在 `size * entry_price`。mark/current notional対応は承認済みの後続課題です。
- Ledger retention/compactionと複数通貨換算は対象外です。
- 実装上の blocker はありません。独立した3回目のT3 reviewとPM acceptanceは未実施です。