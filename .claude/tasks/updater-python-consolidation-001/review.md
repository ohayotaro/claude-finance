Verdict: APPROVE

## Findings by severity

- Critical: None.
- High: None.
- Medium: None.
- Low: None requiring correction.

## Acceptance-criteria mapping

- AC1: PASS. Byte-preserving marker composition and content-addressed DESIGN handling match the `e40f118` reference semantics in [update.py](/Users/ohayotaro/claude-finance/scripts/update.py:137).
- AC2: PASS. [update.sh](/Users/ohayotaro/claude-finance/scripts/update.sh:1) contains only interpreter resolution and delegation. Fixture parity is asserted in [test_update_script.py](/Users/ohayotaro/claude-finance/tests/test_orchestration/test_update_script.py:260).
- AC3: PASS. Marker validation is fail-closed. All 24 local/template, CLAUDE/AGENTS, and missing/duplicate/misordered combinations are collected for both entry points at [test_update_script.py](/Users/ohayotaro/claude-finance/tests/test_orchestration/test_update_script.py:290).
- AC4: PASS. Self-update is restricted to the three enumerated files at [update.py](/Users/ohayotaro/claude-finance/scripts/update.py:53), with the project-owned decoy assertion at [test_update_script.py](/Users/ohayotaro/claude-finance/tests/test_orchestration/test_update_script.py:221).
- AC5: PASS. Standard-library-only imports; corrected forbidden-API scan returned no matches.
- AC6: PASS based on the implementation artifact reporting `208 passed`; independent collection found exactly 208 fast tests and 30 updater tests.
- AC7: PASS. Independent ruff, mypy, `bash -n`, and shellcheck executions passed.
- AC8: PASS based on the implementation artifact. The validator is offline and exercises both entry points.
- AC9: PASS. [README.md](/Users/ohayotaro/claude-finance/README.md:186) documents one implementation, two entry points, F3 discovery, and the three-file self-update.
- F1-F3: PASS. Both-entry-point rejection coverage is present, the corrected AC5 scan passes, and identical resolver logic appears in both shell scripts with the required candidate order.

Acceptance-criteria gaps: None.

## Validation gaps

- This review sandbox is read-only. Pytest execution and the preservation validator could not create temporary files; `uv` likewise could not open its cache. No network access was attempted. The implementation result records successful full executions.
- Windows execution remains intentionally unavailable.
- There is no isolated fixture for a matching pre-existing DESIGN archive while local DESIGN still differs from the template. Creation, skip/deduplication, mismatch rejection, and the matching-reuse implementation were nevertheless reviewed.

## Residual risks

- Financial: None; no trading or financial runtime code changed.
- Operational: Updates remain multi-file and non-atomic; recovery after a late failure is manual. Concurrent updater runs remain unsupported.
- Security: A concurrently modified local template can still introduce TOCTOU exposure outside staged contracts and updater files.
- Regression: Windows behavior is supported only by static construction and review. Full runtime validation should continue on a writable host before PM acceptance.