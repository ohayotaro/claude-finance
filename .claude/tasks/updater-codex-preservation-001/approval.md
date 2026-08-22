# Approval: updater-codex-preservation-001

Status: APPROVED for implementation.

## PM decisions

1. Staged file-overlay design for `.codex` is APPROVED: replace exactly the
   files present in the template `.codex` tree, preserve everything else,
   no-op when the template lacks `.codex`. Fail-closed on symlinks/special
   files and on file-vs-directory ownership conflicts.
2. Dynamic recovery scoped to managed `.codex` files only is APPROVED
   (project-owned plans are neither modified nor copied to temp storage --
   correct for both capacity and confidentiality).
3. Rejected alternatives (copytree merge, fixed whitelist, manifest-driven
   deletion) are reasonable rejections; concurring.
4. Process note: plan.md was delivered in Japanese despite the
   English-artifact rule; content is complete, accepted as-is. Second
   occurrence of this drift (see task
   update-preservation-and-pm-artifact-tracking-001 acceptance note) --
   candidate for a runner prompt-template fix later.
5. DESIGN.md ownership change: user approved folding it into this task
   before implementation started. Brief Addendum 1 (preserve-local /
   copy-if-absent, archive machinery removed, legacy preserved files
   untouchable) is APPROVED as part of the implementation scope. The plan's
   step list extends accordingly; no separate plan cycle is required because
   the addendum is fully enumerated and touches the same components and
   fixtures as the approved plan.

## Addendum 2 approval (2026-08-22)

User-relayed finding, PM-verified: downstream updater tests are stale in all
three repos and fail against the synced updater. Brief Addendum 2 (add the
updater test to `SELF_UPDATE_PATHS`, mixed-ownership decoy assertion for
`tests/`, docs) is APPROVED. The running implementation started before this
addendum, so Addendum 2 is applied in a corrections pass afterwards:

- Corrections tier: mid (`gpt-5.6-terra`) at `high` effort (fully
  enumerated, design approved). Recorded as the required deviation addendum.
- The final pre-acceptance review (strong tier, `high`, full scope) covers
  the base scope plus Addenda 1-2.

## Scope guard

- Approved change surface: `scripts/update.py`,
  `scripts/validate_update_preservation.sh`,
  `tests/test_orchestration/test_update_script.py`, `README.md`.
- Brief forbidden actions remain binding: fixtures only, no Git mutation,
  no network, no runs against the repository root or real downstream repos.

## Acceptance (2026-08-22)

Decision: ACCEPTED.

- Base implementation (`.codex` overlay + Addendum 1 DESIGN preserve-local):
  PASS. Addendum 2 corrections (updater test in `SELF_UPDATE_PATHS`,
  `tests/` decoy): PASS.
- Final review (strong tier, high effort, full scope over base plus Addenda
  1-2): APPROVE, zero findings, no acceptance-criteria gaps.
- PM independent re-verification on the real machine:
  `bash scripts/validate_update_preservation.sh` -> PASS;
  `uv run --extra dev pytest -m "not integration and not slow"` -> 215
  passed.
- Residual risks accepted as recorded by the review (non-atomic multi-file
  mutation with manual recovery, limited TOCTOU, Windows static-only,
  concurrent runs unsupported).
- Review artifact again delivered in Japanese (third occurrence of the
  language drift); accepted as-is, runner prompt-template fix remains a
  backlog item.

## Tier selection

- Plan: strong tier, default matrix (no deviation).
- Implementation: strong tier, default matrix (T2 -> high).
- Review: strong tier, `high` effort at the final pre-acceptance gate, full
  scope.
