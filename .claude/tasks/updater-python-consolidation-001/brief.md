# updater-python-consolidation-001: Consolidate the template updater on a single hardened Python implementation

## Objective

One cross-platform updater implementation. `scripts/update.py` becomes the
single source of updater logic, carrying the hardened preservation design
accepted in task `update-preservation-and-pm-artifact-tracking-001`;
`scripts/update.sh` becomes a thin delegating wrapper kept only as a stable
entry point. The dual-implementation drift risk (which already caused one
stale-test incident) is eliminated.

## Scope

1. Port the accepted hardened design from `scripts/update.sh` (as of commit
   `e40f118`) into `scripts/update.py`, preserving semantics exactly:
   - Preflight marker validation on both local and template `CLAUDE.md` and
     `AGENTS.md`: exactly one full-line occurrence of each boundary marker,
     correct ordering, duplicates rejected; marker text embedded in a prose
     line is content, not a boundary. All validation happens before any
     downstream mutation; failures exit non-zero with the file and marker
     named.
   - Byte-preserving staged composition: template-owned prefix, local Zone B
     / project section, template repo-boundary marker line, local
     post-boundary content. Empty local sections still replace template
     content. No newline normalization beyond what the accepted sh
     implementation does.
   - Content-addressed DESIGN archive: identical naming scheme
     `DESIGN.local-preserved.sha256-<digest>.md`, identical skip/reuse/verify
     semantics, legacy `DESIGN.local-preserved.md` never overwritten or
     removed.
   - Private temporary staging directory (`tempfile.mkdtemp`), no predictable
     project-root backup names; recovery material retained and its location
     printed on post-mutation failure.
   - Behavior documented in the module docstring, matching the sh header.
2. Cross-platform constraints for `update.py`: standard library only, no
   POSIX-only APIs (no `fcntl`), `pathlib`-based paths, chmod of template
   scripts best-effort (skip silently where the platform does not support it).
   Windows cannot be executed in this environment; compliance is by static
   construction and code review, recorded as a residual risk.
3. Replace the body of `scripts/update.sh` with a thin wrapper that delegates
   to `scripts/update.py` with the same working-directory contract and passes
   `TEMPLATE_SOURCE_DIR` / `TEMPLATE_REPO_URL` through the environment.
   Interpreter resolution strategy (e.g. prefer `uv run python`, fall back to
   `python3` with a version check, fail with a clear message) is a plan
   decision for Codex to propose.
4. Updater self-update: the updater MUST copy the template's updater files
   (`scripts/update.py`, `scripts/update.sh`, and the preservation validator
   script) into the downstream project as part of an update, so downstream
   projects stop running stale updaters forever. Only these enumerated
   filenames may be replaced -- never the whole `scripts/` directory, which
   contains project-owned validation scripts downstream. Handle
   replace-while-running ordering safely (a thin exec wrapper and an
   already-loaded Python module are both safe to overwrite; justify in plan).
5. Tests: rework `tests/test_orchestration/test_update_script.py` so both
   entry points assert the hardened behavior (content-addressed archive, Zone
   C preservation, fail-closed on missing/duplicate markers, self-updated
   updater files present). The legacy fixed-name DESIGN expectation for
   update.py is removed together with the legacy behavior.
6. Validator: keep a persistent preservation validator under `scripts/` that
   exercises the Python implementation directly and the sh wrapper at least
   once. Whether it stays a Bash script, becomes Python, or both is a plan
   decision; it must remain self-contained, offline, re-runnable, and
   fail-fast.
7. Docs: update README updater instructions to present one implementation
   with two entry points; fix any statement that implies two independent
   updaters.

## Non-Goals

- No change to the accepted preservation design semantics (marker rules,
  composition, archive naming) beyond the port itself.
- No sync of downstream projects (`~/btc-bbo-mm`, `~/reactvol-re`); follow-up
  after acceptance.
- No changes to `src/`, hooks, `.claude/scripts/codex_handoff.py`,
  `config/registry.toml`, or ignore rules for `.claude/state/` and
  `.claude/logs/`.
- No Windows CI or execution-based Windows testing.

## Acceptance Criteria

- AC1: `scripts/update.py` implements the full hardened design; for the
  fixture scenarios covered by the preservation validator, running the Python
  updater yields byte-identical CLAUDE.md, AGENTS.md, and DESIGN-archive
  outcomes to the accepted sh implementation at `e40f118`.
- AC2: `scripts/update.sh` contains no updater logic beyond delegation, and
  running it end-to-end on a fixture produces the same outcomes as running
  `update.py` directly.
- AC3: Fail-closed marker behavior (missing, duplicate, misordered; local and
  template; embedded-in-prose markers ignored) verified for the Python
  implementation with non-zero exits and unchanged protected content.
- AC4: An update run replaces the downstream copies of exactly the enumerated
  updater files with the template versions, and touches no other file in
  `scripts/`; verified by fixture (a project-owned decoy script in the
  fixture's `scripts/` must survive untouched).
- AC5: `update.py` contains no POSIX-only imports or calls (checked at least
  by grep for `fcntl`, `os.fork`, `pwd`, `grp`, signal-dependent logic) and
  uses only the standard library.
- AC6: Tests updated per scope item 5; full fast suite passes:
  `uv run --extra dev pytest -m "not integration and not slow"`.
- AC7: Lint and type checks pass including the new/changed Python updater:
  `uv run --extra dev ruff check src/ tests/ .claude/hooks/ .claude/scripts/ scripts/update.py`
  and `uv run --extra dev mypy src/ .claude/scripts/ scripts/update.py`
  (mypy strict conventions per coding-principles). `bash -n` and shellcheck
  pass for all shell entry points.
- AC8: The preservation validator passes, exercising both entry points, and
  remains offline (`TEMPLATE_SOURCE_DIR` only).
- AC9: Docs updated per scope item 7; no doc claims two independent updater
  implementations.

## Constraints And Context

- The accepted sh implementation at `e40f118` is the behavioral reference;
  read it before designing the port.
- The dev environment is synced (`uv sync --extra dev` done); all validation
  commands run offline. If a command attempts a network download, stop and
  report BLOCKED.
- Bash 3.2 baseline for any shell code; shellcheck is available locally.
- Plain ASCII only, no emojis. English for all artifacts and code.
- Known-failure-class checklist applies: fail-closed inspections, boundary
  exactness, TOCTOU on staging/backup paths, reserved names (archive and
  staging filenames), duplicate keys (marker uniqueness).
- Network access: not required.

## Risk Tier

T2 - Multi-file port of logic whose failure mode is silent documentation loss
in every downstream project; requires plan, independent review, and PM
acceptance.

## Required Validation

- `uv run --extra dev pytest -m "not integration and not slow"`
- `uv run --extra dev ruff check src/ tests/ .claude/hooks/ .claude/scripts/ scripts/update.py`
- `uv run --extra dev mypy src/ .claude/scripts/ scripts/update.py`
- `bash -n` and `shellcheck` for every shell script touched
- Preservation validator run end-to-end (both entry points), output included
- Fixture evidence for AC1 equivalence and AC4 self-update scoping
- Grep evidence for AC5

## Forbidden Actions

- Do not run any updater against this repository root; fixtures only.
- Do not modify `.claude/` hooks, runner scripts, ignore rules for
  `.claude/state/` or `.claude/logs/`, `src/`, or `config/`.
- Do not commit, push, or mutate Git state; Claude PM owns commits.
- No network access; no new dependencies.

## Open Decisions Or Blockers

- Wrapper interpreter resolution strategy (scope item 3): Codex proposes,
  Claude approves via the plan.
- Validator language/shape (scope item 6): Codex proposes, Claude approves
  via the plan.

## Addendum 1: Corrections scope (PM-approved, 2026-08-22)

The independent review returned CHANGES_REQUIRED with two findings. This
addendum enumerates the corrections pass. All prior scope, constraints, and
forbidden actions remain binding.

- F1 (Medium): In `tests/test_orchestration/test_update_script.py`,
  parameterize the marker rejection cases (missing, duplicate, misordered;
  local and template; CLAUDE and AGENTS) over BOTH entry points -- direct
  Python and the shell wrapper (wrapper cases skipped only when bash is
  unavailable, consistent with the existing success-case parameterization).
  Retain the exit-code, file/marker diagnostic, and unchanged-tree
  assertions for every case.
- F2 (Low): Re-record the AC5 forbidden-API evidence with a corrected,
  token-bounded scan that does not false-positive on `DESIGN` (the reviewer
  confirmed a corrected scan passes). Include the exact corrected command
  and its output in the implementation result. No production code change is
  expected for this finding.
- Re-run and re-record the full required validation suite from the brief
  (pytest fast suite, ruff, mypy, bash -n, shellcheck, preservation
  validator).

Change surface for this pass: `tests/test_orchestration/test_update_script.py`
only. No other file may change unless F1 reveals a genuine wrapper defect, in
which case stop and report BLOCKED instead of expanding scope.

## Addendum 2: Corrections scope (PM-approved, 2026-08-22)

PM acceptance verification on the real development machine found the wrapper
and validator unusable there: `python3` resolves to macOS system Python 3.9.6
and no `python` exists, so `bash scripts/validate_update_preservation.sh`
fails with "ERROR: Python 3.11 or newer is required." The Codex sandbox
happened to have a newer `python3`, which is why validation passed there.
The canonical toolchain guarantee for this project is uv, not a modern bare
`python3`.

- F3: Extend interpreter resolution, used by BOTH `scripts/update.sh` and
  `scripts/validate_update_preservation.sh`, to try in order:
  1. `UPDATER_PYTHON` environment override (path to an interpreter), version
     checked like every other candidate.
  2. `python3`, then `python` (current behavior).
  3. Versioned binaries newest-first: `python3.14`, `python3.13`,
     `python3.12`, `python3.11`.
  4. If `uv` is on PATH: `uv python find '>=3.11'` (offline discovery of an
     already-installed interpreter; the command prints a path). NEVER
     `uv python install` and NEVER `uv run` -- no downloads, no project
     environment synchronization.
  5. Fail with the existing clear diagnostic, now also mentioning
     `UPDATER_PYTHON` and uv.
  Every candidate is validated with the same `>= 3.11` check before use.
  Bash 3.2 compatible. The two scripts may share the logic by duplication;
  keep it small and identical.
- Evidence for F3 must include a successful end-to-end
  `bash scripts/validate_update_preservation.sh` run in THIS repository's
  real environment (where bare `python3` is 3.9.6), not only in a sandbox
  with a modern `python3`.
- README: extend the updater usage section with the `UPDATER_PYTHON`
  override and the uv-based discovery fallback (a few lines; no structural
  rewrite).
- Re-run and re-record the full required validation suite.

Change surface for this pass: `scripts/update.sh`,
`scripts/validate_update_preservation.sh`, `README.md`, and, only if a test
asserts the old resolution diagnostics,
`tests/test_orchestration/test_update_script.py`. No other file may change.
