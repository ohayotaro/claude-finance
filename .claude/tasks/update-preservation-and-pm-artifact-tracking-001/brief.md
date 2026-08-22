# update-preservation-and-pm-artifact-tracking-001: Preserve project knowledge across template updates and track PM artifacts in Git

## Objective

Two related fixes so that (a) PM audit-trail artifacts are version-controlled, and (b) running `scripts/update.sh` in a downstream project never silently destroys project-owned documentation.

## Scope

1. `.gitignore` changes:
   - Stop ignoring `.claude/tasks/`, `.claude/checkpoints/`, and `.claude/plans/`.
   - Add an ignore rule for `.claude/tasks/*/codex-events.jsonl` (large machine replay logs stay local).
   - Keep `.claude/state/` and `.claude/logs/` ignored exactly as they are (`.claude/state/` is a deliberate safety design: live-trading acknowledgments must not propagate across machines, see `.claude/rules/security.md`).
2. `scripts/update.sh` preservation fixes:
   - Preserve CLAUDE.md Zone C: everything after the `@orchestra:repo-boundary` marker line is project-owned working context (see `.claude/rules/document-lifecycle.md`). Back it up before the template copy and restore it afterwards, replacing the template's post-boundary content. Currently only Zone B (between `@orchestra:template-boundary` and `@orchestra:repo-boundary`) is preserved.
   - Preserve the AGENTS.md equivalent: everything after `@codex:repo-boundary` (currently empty in the template, but downstream projects may append).
   - Fix `DESIGN.md` preservation: today the local `DESIGN.md` is copied to the fixed name `.claude/docs/DESIGN.local-preserved.md`, so a second run of `update.sh` overwrites the previously preserved copy with the template version, losing local ADRs. Repeated runs must never destroy a previously preserved local DESIGN.md. Acceptable designs include timestamped preserved filenames, refusing to overwrite an existing preserved file, or skipping preservation when local DESIGN.md is identical to the template version. Choose and justify in the plan.
   - If a boundary marker is missing in a target file, the script must fail loudly (non-zero exit or a prominent error requiring user action), not silently drop the project content.
3. Documentation consistency:
   - `.claude/docs/CODEX_TASK_CONTRACT.md` "Task Directory" section currently states the task directory is gitignored; update it to reflect the new tracking policy (tracked, except `codex-events.jsonl`; still must contain no secrets).
   - Update any other doc lines that assert `.claude/tasks/`, `.claude/checkpoints/`, or `.claude/plans/` are gitignored (search the repo; `README.md` and `.claude/rules/` are likely candidates).
4. Validation script (mandatory persistence per `.claude/rules/coding-principles.md`):
   - Add a self-contained, re-runnable script (e.g. `scripts/validate_update_preservation.sh` or `.py`) that builds a fixture "downstream project" plus a fixture "template source" in a temporary directory, runs `update.sh` with `TEMPLATE_SOURCE_DIR`, and asserts: Zone B preserved, Zone C preserved, AGENTS.md project section and post-boundary section preserved, `backtest-thresholds.json` preserved, DESIGN.md preservation survives two consecutive runs, and missing-marker failure behavior.

## Non-Goals

- No sync of downstream projects (`~/btc-bbo-mm`, `~/reactvol-re`); that is a separate follow-up after this lands in the template.
- No changes to `.claude/state/` or `.claude/logs/` ignore status.
- No changes to runtime code under `src/`, hooks behavior, or the codex_handoff runner.
- No git history rewriting or retroactive import of previously untracked task artifacts beyond what `git add` naturally picks up.

## Acceptance Criteria

- AC1: After the `.gitignore` change, `git check-ignore` confirms `.claude/tasks/x/brief.md`, `.claude/checkpoints/x.md`, `.claude/plans/x.md` are NOT ignored, while `.claude/tasks/x/codex-events.jsonl`, `.claude/state/x.ack`, `.claude/logs/x.log` ARE ignored.
- AC2: Running `update.sh` (via `TEMPLATE_SOURCE_DIR` against a fixture) on a project whose CLAUDE.md Zone C differs from the template preserves the project's Zone C verbatim (modulo a single trailing-newline normalization at most), and same for Zone B and the AGENTS.md sections.
- AC3: Two consecutive `update.sh` runs never lose a locally modified DESIGN.md: after both runs, the local content is still recoverable from a preserved file.
- AC4: When a target file lacks its boundary markers, `update.sh` fails loudly before or instead of discarding project content; the failure mode is documented in the script header comment.
- AC5: `.claude/docs/CODEX_TASK_CONTRACT.md` and any other docs no longer claim the task directory is gitignored; no doc contradicts the new `.gitignore`.
- AC6: The validation script exists under `scripts/`, is self-contained, re-runnable, exits non-zero on any assertion failure, and passes.
- AC7: `uv run --extra dev pytest -m "not integration and not slow"` still passes, and lint/type checks pass for any touched Python files.

## Constraints And Context

- This repository IS the template origin. `update.sh` executes in downstream projects; fixes here must work when the template is cloned or provided via `TEMPLATE_SOURCE_DIR`.
- `update.sh` marker matching uses awk regex matching and Python `str.find`; watch boundary exactness (marker string appearing inside preserved content, first-occurrence matching) and fail-closed behavior on missing markers.
- Known-failure-class checklist applies: fail-closed inspections, boundary exactness, TOCTOU (backup files in the working directory), reserved names (backup filenames could collide with user files).
- Plain ASCII only, no emojis, per `.claude/rules/language.md`.
- Shell code: keep `set -euo pipefail`; validate with `bash -n` at minimum, `shellcheck` only if already available locally (do not add dependencies).
- Network access: not required (use `TEMPLATE_SOURCE_DIR` in tests; never clone from the network in validation).

## Risk Tier

T2 - Multi-file change; the update.sh backup/restore logic has a silent-data-loss failure mode affecting every downstream project, so it needs a plan, independent review, and PM acceptance.

## Required Validation

- `bash -n scripts/update.sh`
- The new validation script run end-to-end, output included in the result.
- `git check-ignore` evidence for AC1 (exact commands and outcomes).
- `uv run --extra dev pytest -m "not integration and not slow"`
- `uv run --extra dev ruff check src/ tests/ .claude/hooks/ .claude/scripts/` (plus the new script if Python)
- `uv run --extra dev mypy src/ .claude/scripts/` (plus the new script if Python)

## Forbidden Actions

- Do not modify `.claude/state/` or `.claude/logs/` ignore rules.
- Do not run `update.sh` against this repository root itself; exercise it only inside temporary fixture directories.
- Do not touch `src/`, `config/registry.toml`, hooks, or `.claude/scripts/codex_handoff.py`.
- Do not commit, push, or perform any Git mutation beyond reading state (`git check-ignore`, `git status`); Claude PM owns commits.
- No network access.

## Open Decisions Or Blockers

- DESIGN.md preservation mechanism (timestamped vs refuse-to-overwrite vs content-diff skip): Codex proposes in the plan, Claude approves.
- Whether `codex-<phase>.stderr.txt` files should also be ignored alongside `codex-events.jsonl`: Codex may propose either way with rationale; default is to track them (small, useful failure evidence).

## Addendum 1: Corrections scope (PM-approved, 2026-08-22)

The first implementation pass returned BLOCKED with AC1-AC6 PASS. This
addendum enumerates the corrections pass. Scope is exactly the items below;
all prior scope, constraints, and forbidden actions remain binding.

- F1: Update `tests/test_orchestration/test_update_script.py` so the two
  updater tests no longer share the DESIGN-archive assertion:
  - The `update.sh` test must assert that the local DESIGN content
    ("local design") is preserved in a content-addressed archive matching
    `DESIGN.local-preserved.sha256-<digest>.md` (compute the expected digest
    or glob for the pattern and compare content), and that no fixed-name
    `DESIGN.local-preserved.md` is created by the shell updater for this
    fixture.
  - The `update.py` test keeps the legacy fixed-name expectation unchanged
    (`update.py` is deferred and untouched).
  - Additionally, the `update.sh` test must assert Zone C preservation: the
    fixture's post-`@orchestra:repo-boundary` content ("old context") is
    present in the updated `CLAUDE.md`.
  - Shared scaffolding may be refactored minimally to support the split; do
    not change fixture inputs otherwise.
- F2: Re-run the full required validation suite from the brief. The PM has
  synced the dev environment via `uv sync --extra dev`, so plain
  `uv run --extra dev pytest -m "not integration and not slow"`, ruff, and
  mypy commands now run without downloads. Network remains forbidden; if a
  command still attempts a download, stop and report BLOCKED.

Change surface for this pass: `tests/test_orchestration/test_update_script.py`
only. No other file may change.
