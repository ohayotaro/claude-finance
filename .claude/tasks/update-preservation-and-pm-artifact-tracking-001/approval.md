# Approval: update-preservation-and-pm-artifact-tracking-001

Status: APPROVED for implementation.

## PM decisions on open items

1. DESIGN.md preservation mechanism: content-addressed archive
   (`DESIGN.local-preserved.sha256-<digest>.md`) is approved. Deterministic,
   deduplicates identical runs, retains multiple distinct local revisions,
   never touches the legacy `DESIGN.local-preserved.md`.
2. `codex-<phase>.stderr.txt`: tracked (not ignored), as planned. Small,
   useful failure evidence; no-secrets rule applies.
3. `scripts/update.py`: confirmed present with equivalent defects. Deferral is
   approved; it stays out of scope. A separate follow-up task will decide
   parity fix vs deprecation. Do not modify it in this task.
4. Fail-closed marker preflight (exactly one full-line occurrence of each
   marker, correct ordering, duplicates rejected, template and downstream both
   validated before mutation) is approved, including the consequence that
   malformed downstream contracts stop updating until manually repaired.

## Scope guard

- The plan's impacted-file list is approved as the change surface:
  `.gitignore`, `scripts/update.sh`, `scripts/validate_update_preservation.sh`
  (new), `.claude/docs/CODEX_TASK_CONTRACT.md`, `README.md`, and a resolution
  annotation in `.claude/docs/reviews/codex-meta-review-2026-05-09.md`.
- Forbidden actions in the brief remain binding, including: no runs of
  `update.sh` against this repository root, no Git mutations, no network.

## Tier selection

- Plan: strong tier, default matrix (no deviation).
- Implementation: strong tier, default matrix (T2 -> high). First
  implementation, not a corrections pass, so no mid-tier economization.
- Review: strong tier, high effort at the final pre-acceptance gate.

## Addendum 1 approval (2026-08-22)

First implementation pass: AC1-AC6 PASS, AC7 BLOCKED on (a) a stale legacy
test assertion and (b) an unsynced dev environment.

- Brief Addendum 1 (corrections scope F1-F2) is APPROVED. The change surface
  extension to `tests/test_orchestration/test_update_script.py` is authorized;
  the split (shell updater expects the content-addressed archive, Python
  updater keeps the legacy expectation) matches the approved design and does
  not relax any acceptance criterion.
- Environment: PM ran `uv sync --extra dev` so the locked toolchain is
  available offline. AC7 must now be satisfied with the exact brief commands.
- Tier selection for the corrections pass: mid tier (`gpt-5.6-terra`) at
  `high` effort per the corrections policy in codex-delegation.md (every
  finding enumerated, design approved). Recorded here as the deviation
  addendum required by that policy.
- Final pre-acceptance review remains strong tier at `high` effort, full
  scope.

## Acceptance (2026-08-22)

Decision: ACCEPTED.

- Corrections implementation result: PASS on all AC1-AC7 with exact command
  evidence.
- Independent review (strong tier, high effort, fresh invocation): APPROVE,
  zero findings at any severity, no acceptance-criteria or validation gaps.
- Review-environment gap (read-only sandbox could not re-run the fixture
  validator and pytest) was closed by the PM re-running both locally:
  `bash scripts/validate_update_preservation.sh` -> PASS;
  `uv run --extra dev pytest -m "not integration and not slow"` -> 180 passed.
- Financial safeguards: no runtime or financial-logic changes; `.claude/state/`
  and `.claude/logs/` ignore rules unchanged.
- Process note: review.md was delivered in Japanese despite the
  English-artifact language rule; content is complete, accepted as-is,
  flagged as minor prompt drift for the runner review template.
- Follow-up (not part of this task): decide parity fix vs deprecation for
  `scripts/update.py`, which retains the legacy preservation defects.
