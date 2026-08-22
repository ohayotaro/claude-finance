# updater-codex-preservation-001: Stop the template updater from deleting project-owned .codex content

## Objective

The updater currently does the equivalent of `rm -rf .codex` and copies the
template `.codex` tree. During the 2026-08-22 downstream sync this deleted 29
project-owned research plan documents under `~/reactvol-re/.codex/plans/`
(28 restored from git, 1 untracked file reconstructed from the authoring
Codex session log). Fix: `.codex` must be treated as a mixed-ownership
directory -- template-managed files are replaced, everything else is
preserved.

## Scope

1. In `scripts/update.py`, replace the wholesale `.codex` removal+copy with
   file-level replacement:
   - For every file in the template's `.codex` tree, create or replace the
     corresponding downstream path (creating parent directories as needed).
   - Never delete or modify any other downstream `.codex` path. Files and
     directories that exist downstream but not in the template are preserved
     untouched (e.g. `.codex/plans/`).
   - A missing template `.codex` leaves the downstream `.codex` untouched
     (do not delete it, unlike the current behavior).
   - Template-managed `.codex` files participate in the existing preflight
     safety checks (safe regular files) and recovery-copy mechanism before
     mutation.
2. Update the module docstring / safety contract to state the mixed-ownership
   `.codex` semantics.
3. Fixtures: extend `scripts/validate_update_preservation.sh` and
   `tests/test_orchestration/test_update_script.py` with a project-owned
   decoy under the downstream fixture's `.codex/plans/` (both a git-style
   tracked file and an extra file are unnecessary to distinguish -- one decoy
   file suffices) asserting byte-identical survival across an update, plus an
   assertion that the template-managed `.codex/config.toml` is replaced.
4. README: adjust wording if it describes `.codex` replacement semantics.

## Non-Goals

- No change to `.claude/hooks|rules|skills|scripts` replacement semantics
  (those directories are wholly template-owned by contract).
- No re-sync of downstream repos in this task.
- No changes to `src/`, hooks, runner, registry, or ignore rules.

## Acceptance Criteria

- AC1: Fixture proves a downstream `.codex/plans/decoy.md` survives an update
  byte-identically while `.codex/config.toml` is replaced with the template
  version.
- AC2: Fixture proves a downstream-only `.codex` (template lacking `.codex`)
  is left fully untouched.
- AC3: Existing preservation guarantees (Zone B/C, AGENTS sections, DESIGN
  archives, self-update scoping, fail-closed markers) still pass -- full
  validator run and updater test suite green.
- AC4: `uv run --extra dev pytest -m "not integration and not slow"` passes;
  ruff and mypy (including `scripts/update.py`) pass; `bash -n` and
  shellcheck pass for touched shell scripts.
- AC5: Docstring and README (if applicable) describe the mixed-ownership
  `.codex` semantics; no doc claims wholesale `.codex` replacement.

## Constraints And Context

- The accepted implementation at `54d7cf7` is the base; keep its structure
  (typed helpers, staging, recovery) and only change the `.codex` step.
- Standard library only; cross-platform constraints from
  `updater-python-consolidation-001` still apply.
- Offline validation only (`TEMPLATE_SOURCE_DIR` fixtures); dev environment
  is synced.
- Plain ASCII, English artifacts.

## Risk Tier

T2 - Updater logic in the silent-data-loss failure class; the current
behavior already caused a real deletion incident downstream.

## Required Validation

- `bash scripts/validate_update_preservation.sh` (end-to-end, output included)
- `uv run --extra dev pytest -m "not integration and not slow"`
- `uv run --extra dev ruff check src/ tests/ .claude/hooks/ .claude/scripts/ scripts/update.py`
- `uv run --extra dev mypy src/ .claude/scripts/ scripts/update.py`
- `bash -n` and `shellcheck` for touched shell scripts

## Forbidden Actions

- Do not run any updater against this repository root or any real downstream
  repository; fixtures only.
- Do not commit, push, or mutate Git state.
- No network access; no new dependencies.

## Open Decisions Or Blockers

None; the design is enumerated above.

## Addendum 1: DESIGN.md ownership change (PM-approved, user-approved, 2026-08-22)

User decision: `.claude/docs/DESIGN.md` switches from replace-and-archive to
preserve-local. Rationale: per `.claude/rules/document-lifecycle.md` the file
accumulates project ADRs and is effectively project-owned; replace-and-archive
created a manual-merge burden in every downstream repo on every sync.

Enumerated changes (same task, same change surface plus this scope):

- A1: Remove `docs/DESIGN.md` from the template-managed `.claude` file
  replacement list in `scripts/update.py`. New semantics: if the downstream
  `.claude/docs/DESIGN.md` exists, it is left byte-untouched; if absent, the
  template's DESIGN.md is copied once as the initial scaffold.
- A2: Remove the DESIGN content-addressed archive machinery (comparison,
  staging, `DESIGN.local-preserved.sha256-*.md` creation and verification)
  from the updater -- it is obsolete once DESIGN.md is never replaced.
  Existing `DESIGN.local-preserved*` files in downstream repos are data, not
  updater state: the updater must never touch them.
- A3: Update tests and validator: replace the DESIGN-archive fixtures with
  (a) local DESIGN.md byte-identical survival across an update and across a
  second run, (b) absent DESIGN.md receives the template copy, (c) any
  pre-existing `DESIGN.local-preserved*` file survives untouched.
- A4: Docstring and README describe the preserve-local / copy-if-absent
  semantics; remove archive wording.
- Other `.claude` template-managed files (`settings.json`,
  `docs/CODEX_TASK_CONTRACT.md`) keep their replace semantics;
  `backtest-thresholds.json` keeps its preserve semantics.

Acceptance criteria additions:

- AC6: Fixtures prove A1/A2/A3 semantics for both entry points where the
  existing parameterization applies.
- AC7: No updater code path can write or delete a `DESIGN.local-preserved*`
  path (verified by search and by the survival fixture).

Note for downstream (out of scope here): after this lands, each downstream
repo should restore its local DESIGN.md content from its
`DESIGN.local-preserved.sha256-*.md` archive created during the 2026-08-22
sync.

## Addendum 2: Self-update must include the updater test (PM-approved, 2026-08-22)

External finding relayed by the user, verified by the PM: all three
downstream repos hold stale copies of
`tests/test_orchestration/test_update_script.py` asserting legacy updater
behavior (fixed-name DESIGN archive), so their test suites fail against the
newly synced updater. The updater keeps its scripts in lockstep via
`SELF_UPDATE_PATHS` (scripts/update.py:60) but not its test, which
reintroduces exactly the code/test drift class this template eliminates.

Enumerated changes:

- B1: Add `tests/test_orchestration/test_update_script.py` to
  `SELF_UPDATE_PATHS`. It participates in the existing preflight, recovery,
  and enumerated-file replacement mechanics; ordering stays "wrapper last".
- B2: Fixtures (pytest and validator): assert the downstream test file is
  replaced with the template version during an update, and that a
  project-owned decoy elsewhere under the fixture's `tests/` tree survives
  untouched (mixed-ownership guarantee, mirroring the `scripts/` decoy).
- B3: Docstring and README self-update descriptions list four files.

Acceptance criteria addition:

- AC8: Fixture evidence for B1/B2; docs consistent per B3.
