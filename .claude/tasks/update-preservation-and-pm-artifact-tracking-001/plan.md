# Plan

## Recommended design and rationale

### 1. Git tracking policy

Update [.gitignore](/Users/ohayotaro/claude-finance/.gitignore:31) to:

- Remove the blanket ignores for `.claude/tasks/`, `.claude/checkpoints/`, and `.claude/plans/`.
- Add `.claude/tasks/*/codex-events.jsonl`.
- Leave `.claude/state/` and `.claude/logs/` unchanged.
- Continue tracking `codex-<phase>.stderr.txt`. These files are small and useful failure evidence; the task-directory no-secrets rule applies to them.

This makes PM briefs, plans, approvals, results, reviews, checkpoints, and state metadata auditable through Git while excluding the large replay log.

### 2. Fail-closed, byte-preserving contract restoration

Refactor [scripts/update.sh](/Users/ohayotaro/claude-finance/scripts/update.sh:1) around a preflight-and-stage flow:

- Retain `set -euo pipefail`.
- Use a private `mktemp -d` work directory with restrictive permissions instead of predictable project-root backup names such as `.zone-b.backup.md`.
- Place a remote clone, when used outside validation, inside that private directory rather than `.starter-update`.
- Require both local and template `CLAUDE.md` and `AGENTS.md`.
- Before any downstream mutation, require exactly one full-line occurrence of every boundary marker and verify correct ordering.
- Treat marker text embedded within a normal prose line as content, not a boundary.
- Reject duplicate exact marker lines because their intended boundary is ambiguous.
- Build complete staged versions of both contract files before copying anything:
  - Template-owned prefix remains from the incoming template.
  - Zone B/project section comes from the downstream file.
  - The repo-boundary marker comes from the template.
  - Everything after the repo-boundary marker comes from the downstream file.
- Operate on bytes or line slices retaining original terminators, avoiding `awk` normalization, `str.find`, `rstrip`, and the current empty-section skip. Empty local sections must also replace template content correctly.
- Copy staged contracts only after all marker validation and composition succeeds.
- Keep recovery material on a post-mutation failure and print its exact location; remove it only after a successful update.
- Document in the script header that missing, duplicated, or misordered markers cause a non-zero exit before template-managed content is replaced.

This directly removes the substring, first-occurrence, empty-section, and silent-success failure modes.

### 3. Content-addressed DESIGN preservation

Before replacing `.claude/docs/DESIGN.md`:

- Compare the downstream file with the incoming template file.
- If identical, do not create an archive because the active file remains recoverable from the template.
- If different, preserve the downstream bytes as a content-addressed file such as:
  `DESIGN.local-preserved.sha256-<full-digest>.md`.
- If that archive already exists with identical content, reuse it.
- If the expected archive path exists with different content or is an unsafe file type, fail before replacing `DESIGN.md`.
- Never overwrite or remove the legacy `DESIGN.local-preserved.md`; downstream projects may already depend on it.

A content-addressed archive is deterministic, naturally deduplicates consecutive runs, avoids timestamp collisions, and supports multiple distinct local revisions.

### 4. Documentation consistency

Update:

- [.claude/docs/CODEX_TASK_CONTRACT.md](/Users/ohayotaro/claude-finance/.claude/docs/CODEX_TASK_CONTRACT.md:21) to state that task artifacts are tracked, except `codex-events.jsonl`, and that no task artifact may contain secrets.
- [README.md](/Users/ohayotaro/claude-finance/README.md:80) to identify tracked task artifacts and mark `codex-events.jsonl` as local-only.
- [.claude/docs/reviews/codex-meta-review-2026-05-09.md](/Users/ohayotaro/claude-finance/.claude/docs/reviews/codex-meta-review-2026-05-09.md:18) with a resolution note clarifying that its ignore-rule finding describes historical state. Do not rewrite the historical finding.
- Any further present-tense contradictory statement found by the final repository-wide search.

No current `.claude/rules/` file claims these artifact directories are ignored.

### 5. Persistent validation script

Add `scripts/validate_update_preservation.sh`, compatible with the repository’s Bash 3.2 baseline.

It will:

- Locate the repository updater relative to its own path.
- Create isolated downstream and template fixtures with `mktemp -d`.
- Always set `TEMPLATE_SOURCE_DIR`; it will never clone or access the network.
- Clean its fixture directory through a scoped trap.
- Run the actual repository `scripts/update.sh` from inside the downstream fixture.
- Exit non-zero with a clear assertion message on any failure.
- Verify:
  - CLAUDE Zone B byte content.
  - CLAUDE post-boundary Zone C byte content.
  - AGENTS project section and post-boundary content.
  - Embedded marker tokens in prose are not treated as boundaries.
  - Empty preserved sections are handled correctly.
  - `backtest-thresholds.json` remains local.
  - A modified DESIGN is recoverable after two updates.
  - The second run does not overwrite a legacy or content-addressed archive.
  - Existing files using the updater’s former backup names are untouched.
  - Missing start/end markers in downstream CLAUDE or AGENTS produce non-zero status and leave protected target content unchanged.
  - Missing or ambiguous markers in the template also fail before target mutation.
  - No network path is entered.

## Alternatives considered

- Timestamped DESIGN archives: simple, but can collide, create duplicate template snapshots, and make repeatability weaker.
- Refuse to run when `DESIGN.local-preserved.md` exists: prevents overwriting but makes routine repeated updates unusable.
- Fixed archive plus content-diff skip: fixes the immediate second-run case but cannot retain multiple distinct local revisions safely.
- Continue using `awk` and Python `str.find`: rejected because regex/substring matching cannot enforce exact, unique marker lines and currently normalizes or skips content.
- Modify `scripts/update.py` in the same change: deferred because the approved scope and mandatory fixture explicitly target `scripts/update.sh`. The Python updater has equivalent defects and should receive a separately approved parity task or deprecation decision.

## Impacted files/components

Planned modifications:

- `.gitignore`
- `scripts/update.sh`
- `scripts/validate_update_preservation.sh` (new)
- `.claude/docs/CODEX_TASK_CONTRACT.md`
- `README.md`
- `.claude/docs/reviews/codex-meta-review-2026-05-09.md` (resolution annotation)

Explicitly untouched:

- `.claude/state/` and `.claude/logs/` ignore rules
- `scripts/update.py`
- `src/`
- `config/registry.toml`
- Hooks and `.claude/scripts/codex_handoff.py`
- Downstream repositories

## Implementation sequence

1. Await Claude PM approval because this is T2.
2. Recheck `git status` and preserve any new unrelated changes.
3. Change `.gitignore` and verify individual ignore decisions immediately.
4. Refactor `update.sh`:
   - private temporary workspace;
   - local/template preflight;
   - exact marker parsing;
   - staged contract composition;
   - content-addressed DESIGN archive;
   - protected threshold restoration;
   - explicit failure/recovery behavior.
5. Add the fixture validation script.
6. Update the contract, README, and historical-review resolution note.
7. Run the complete validation set below without invoking `update.sh` in this repository root.
8. Record exact outputs and acceptance evidence in the implementation result.
9. Submit the change for a fresh read-only Codex review and Claude PM acceptance.

## Test and validation plan

Shell validation:

```bash
bash -n scripts/update.sh
bash -n scripts/validate_update_preservation.sh
shellcheck scripts/update.sh scripts/validate_update_preservation.sh
bash scripts/validate_update_preservation.sh
```

`shellcheck` is already installed locally, so it will be used without adding a dependency.

Ignore-policy evidence:

```bash
for path in \
  .claude/tasks/x/brief.md \
  .claude/checkpoints/x.md \
  .claude/plans/x.md
do
  if git check-ignore -q --no-index "$path"; then
    printf 'unexpectedly ignored: %s\n' "$path"
    exit 1
  fi
  printf 'not ignored: %s\n' "$path"
done

git check-ignore -v --no-index \
  .claude/tasks/x/codex-events.jsonl \
  .claude/state/x.ack \
  .claude/logs/x.log
```

Expected result: the first loop reports all three paths as not ignored; the second command reports the exact matching ignore rules for all three local-only paths.

Documentation consistency:

```bash
rg --hidden -n -i --glob '!.git/**' \
  '(gitignore|gitignored|ignored|untracked).*\.claude/(tasks|checkpoints|plans)|\.claude/(tasks|checkpoints|plans).*(gitignore|gitignored|ignored|untracked)' \
  .
```

Any remaining match must either describe the new policy or be explicitly labeled historical and resolved.

Repository regression checks:

```bash
uv run --extra dev pytest -m "not integration and not slow"
uv run --extra dev ruff check src/ tests/ .claude/hooks/ .claude/scripts/
uv run --extra dev mypy src/ .claude/scripts/
```

No Python file is planned for modification, so no extra Python lint/type target is needed. No dependency installation or network access will be attempted. If the existing environment cannot run required commands without downloading dependencies, implementation must stop and report `BLOCKED`.

## Risks and blockers

- Existing downstream contracts with missing, duplicate, or misplaced markers will stop updating. This is intentional fail-closed behavior; the error must identify the file and marker requiring manual repair.
- Multi-file replacement cannot be fully atomic. Staging all protected contracts first and retaining recovery material on failure minimizes this risk.
- Content-addressed DESIGN archives can accumulate when projects create genuinely distinct local versions. This is intentional audit preservation, with identical versions deduplicated.
- `scripts/update.py` remains an equivalent data-loss risk for anyone invoking that undocumented alternate updater. It is outside the current approved scope and should be handled separately.
- The validator must avoid Bash features newer than the installed Bash 3.2.
- No current planning blocker exists. Network access is unnecessary.

## Acceptance-criteria mapping

| Criterion | Planned coverage |
|---|---|
| AC1 | Remove the three directory ignores, add only the JSONL rule, retain state/log rules unchanged, and run the six-path `git check-ignore` checks. |
| AC2 | Exact byte-slice contract composition preserves CLAUDE Zone B/Zone C and both AGENTS sections; fixture comparisons exercise differing template content and embedded marker text. |
| AC3 | Content-addressed, no-overwrite DESIGN archives plus a two-run regression fixture retain the original local design and legacy archives. |
| AC4 | Preflight requires exact, unique, ordered markers before mutation; the header documents non-zero failure; fixture cases assert failure and unchanged protected content. |
| AC5 | Update the canonical contract and README, annotate the historical review, then run a repository-wide contradiction search. |
| AC6 | Add a self-contained temporary-fixture shell validator, run it twice safely, and require non-zero exits for every failed assertion. |
| AC7 | Run the complete fast pytest, ruff, and mypy commands; also run `bash -n` and locally available `shellcheck` for both touched shell scripts. |