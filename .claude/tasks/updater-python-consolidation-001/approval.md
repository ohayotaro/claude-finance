# Approval: updater-python-consolidation-001

Status: APPROVED for implementation.

## PM decisions on open items

1. Wrapper interpreter resolution: APPROVED as planned -- direct `python3`
   then `python` with a >= 3.11 version check and clear failure diagnostics,
   using `exec`. Deliberately not `uv run` so the entry point never triggers
   dependency synchronization or downloads. Direct
   `uv run python scripts/update.py` remains available and documented.
2. Validator shape: APPROVED as planned -- keep the existing Bash validator
   filename (`scripts/validate_update_preservation.sh`), extend it to
   exercise the Python entry point for the full hardened scenario set, the sh
   wrapper end-to-end on an equivalent fixture, and byte-for-byte parity
   between the two. Windows users invoke `update.py` directly; this is the
   documented limitation.
3. Self-update tuple and ordering: APPROVED -- exactly `scripts/update.py`,
   `scripts/validate_update_preservation.sh`, then `scripts/update.sh` last;
   never the whole `scripts/` directory; decoy-survival evidence required.
4. README change removing the remote `bash <(curl ...)` example: APPROVED --
   a delegating wrapper cannot run standalone; keeping the example would be a
   trap.
5. Post-mutation failure injection test: APPROVED as a test-only hook; no
   injection affordances may weaken the production path.

## Scope guard

- Approved change surface: `scripts/update.py`, `scripts/update.sh`,
  `scripts/validate_update_preservation.sh`,
  `tests/test_orchestration/test_update_script.py`, `README.md`. No other
  file may change.
- Brief forbidden actions remain binding: fixtures only, no Git mutation, no
  network, no new dependencies.

## Tier selection

- Plan: strong tier, default matrix (no deviation).
- Implementation: strong tier, default matrix (T2 -> high). First
  implementation of an open-ended port; no economization.
- Review: strong tier, `high` effort at the final pre-acceptance gate, full
  scope.

## Addendum 1 approval (2026-08-22)

First independent review (strong tier, high effort): CHANGES_REQUIRED with
one Medium finding (rejection tests not parameterized over the shell
wrapper) and one Low finding (invalid AC5 grep evidence; corrected scan
passes). Both findings are fully enumerated in Brief Addendum 1 and the
fixes are design-approved.

- Corrections pass: APPROVED. Change surface is
  `tests/test_orchestration/test_update_script.py` only; fail closed
  (report BLOCKED) if a genuine wrapper defect surfaces.
- Tier selection for the corrections pass: mid tier (`gpt-5.6-terra`) at
  `high` effort per the corrections policy (every finding enumerated,
  design approved). Recorded here as the required deviation addendum.
- After corrections, the final pre-acceptance review re-runs on the strong
  tier at `high` effort, full scope, per policy rule 1 (the last gate is
  never economized).

## Addendum 2 approval (2026-08-22)

The second review returned APPROVE, but PM acceptance verification on the
real development machine failed: bare `python3` is 3.9.6 there, so the
wrapper and validator cannot resolve an interpreter. Acceptance is WITHHELD
until fixed. Brief Addendum 2 (F3: interpreter resolution extended with
`UPDATER_PYTHON` override, versioned binaries, and offline
`uv python find '>=3.11'` fallback; evidence required from the real
environment) is APPROVED with the enumerated design.

- Tier selection: corrections on mid tier (`gpt-5.6-terra`) at `high`
  effort (finding enumerated, design approved). Recorded as the required
  deviation addendum.
- The final pre-acceptance review re-runs on the strong tier at `high`
  effort, full scope, after these corrections.
- PM will additionally re-verify the validator and fast suite locally
  before acceptance, as with prior gates.

## Acceptance (2026-08-22)

Decision: ACCEPTED.

- Final review (strong tier, high effort, fresh invocation, full scope):
  APPROVE with zero findings; F1-F3 all confirmed resolved.
- PM independent re-verification on the real development machine (the
  environment that exposed the F3 interpreter gap):
  `bash scripts/validate_update_preservation.sh` -> PASS (exit 0);
  `uv run --extra dev pytest -m "not integration and not slow"` -> 208
  passed; ruff -> All checks passed; mypy -> no issues in 14 files.
- Financial safeguards: no trading, risk-control, registry, or `src/`
  changes.
- Residual risks accepted and recorded: Windows compliance is
  static-construction only (no Windows execution available); concurrent
  updater runs unsupported; multi-file replacement non-atomic with manual
  recovery from retained material; template TOCTOU outside staged files;
  `shutil.copytree` dereferences symlinks (template currently has none).
- Review note: the second review suggested a fixture for "pre-existing
  matching archive while local DESIGN differs"; non-blocking, may be added
  opportunistically in a future test task.
- Follow-up (separate effort): sync downstream projects (`~/btc-bbo-mm`,
  `~/reactvol-re`) by copying the new updater files first, then running the
  updater; their stale updaters must not be executed.
