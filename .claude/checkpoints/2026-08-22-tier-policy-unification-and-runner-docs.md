# Checkpoint: 2026-08-22 - Tier policy unification and runner docs fix

## Session Summary

Unified the Codex model/effort selection policy across the template and both downstream projects, then fixed runner invocation docs after a real interpreter failure. All engineering ran through the canonical runner; both tasks T1, implemented by Codex on light tier (gpt-5.6-luna, medium) per the new policy itself.

## Tasks

### codex-delegation-tier-policy-001 (T1) - ACCEPTED

- Brief: `.claude/tasks/codex-delegation-tier-policy-001/brief.md`
- Result: `.claude/tasks/codex-delegation-tier-policy-001/implementation-result.md` (PASS)
- Acceptance: `.claude/tasks/codex-delegation-tier-policy-001/acceptance.md`
- State: `.claude/tasks/codex-delegation-tier-policy-001/state.json`
- Outcome: `## Model And Effort Tier Policy` section added to `.claude/rules/codex-delegation.md`; pointer added to `.claude/docs/CODEX_TASK_CONTRACT.md`. User decisions: corrections implement = mid tier (terra) at HIGH effort; template-first update; immediate downstream sync.

### runner-docs-uv-python-001 (T1) - ACCEPTED

- Brief: `.claude/tasks/runner-docs-uv-python-001/brief.md`
- Result: `.claude/tasks/runner-docs-uv-python-001/implementation-result.md` (PASS)
- Acceptance: `.claude/tasks/runner-docs-uv-python-001/acceptance.md`
- Outcome: `python3 .claude/scripts/codex_handoff.py` replaced with `uv run python .claude/scripts/codex_handoff.py` in 5 files / 26 places (README, contract, codex-delegation rules, codex-task and codex-review skills) plus a Python 3.11+ note after both runner blocks. Root cause: macOS system python3 is 3.9; `datetime.UTC` import crashed the runner on first invocation this session.

## Downstream Sync (completed, user-approved)

- btc-bbo-mm and reactvol-re received byte-identical copies of: `.claude/rules/codex-delegation.md`, `.claude/docs/CODEX_TASK_CONTRACT.md`, `.claude/skills/codex-task/SKILL.md`, `.claude/skills/codex-review/SKILL.md`.
- Downstream READMEs contain no runner invocation; no README changes needed there.
- Supersede notes added: `~/reactvol-re/.claude/state/codex-model-tier-policy.md` (marked superseded, values match unified policy) and `~/btc-bbo-mm/.claude/plans/bitflyer-cfd-port-roadmap.md` (dated bullet: corrections implements now terra/HIGH, was medium).

## Validation Status

- Both tasks: all acceptance criteria verified by PM grep/diff; details in each `acceptance.md`.
- Post-sync: template and both downstream copies verified identical; zero old-invocation matches outside `.claude/tasks/` in all three repos.

## Uncommitted State (action needed)

- claude-finance: `README.md`, `.claude/docs/CODEX_TASK_CONTRACT.md`, `.claude/rules/codex-delegation.md`, both skill files - modified, uncommitted.
- btc-bbo-mm: the 4 synced files - modified, uncommitted.
- reactvol-re: the 4 synced files - modified, uncommitted; ALSO carries unrelated pre-existing uncommitted changes (`evidence-inventory-convention.md`, `vendor-reactvol-architecture-map.md`, `.gitignore`, `scripts/`, `src/strategies/reactvol_re/backtester.py`). Commit the sync separately from those.

## Blockers

None. (Codex usage limit reported earlier on 2026-08-22 in btc-bbo-mm was not encountered; user confirmed Codex usable and both runs succeeded.)

## Next Action

- Optional T1 candidate: interpreter version guard in `.claude/scripts/codex_handoff.py` (clear error on Python < 3.11). Recorded in both acceptance files; not started.

## Update (same day): Git ownership change and commits

- User assigned routine Git management to Claude PM. CLAUDE.md ownership sections updated in all three repos: PM owns staging, Conventional Commits of accepted work, and pushes; destructive Git operations (history rewrite, force push, hard reset, branch deletion) remain excluded.
- claude-finance: committed `7f49fd5` (tier policy + runner docs) and `14dd78b` (git ownership), pushed to origin/main.
- btc-bbo-mm: committed `4b4b752`, pushed. reactvol-re: committed `572d9d5`, pushed. Each commit contains only the 4 synced files plus CLAUDE.md; reactvol-re's unrelated pre-existing changes were left uncommitted.
- Local `git config user.name/user.email` set in all three repos (was unset; the two template commits `7f49fd5`/`14dd78b` carry an auto-derived committer identity - cosmetic, fixable only by history rewrite, left as-is pending user decision).

## Update 2: Downstream push scope verified; new push rule

- User questioned the downstream pushes. Verified with `git show --stat`: btc-bbo-mm `4b4b752` and reactvol-re `572d9d5` contain exactly the 5 template-derived files each (identical 58/21 diff stat to the template commits); reactvol-re's in-flight research work (src, tests, scripts, reports, task artifacts) remains uncommitted and untouched. User accepted.
- Operating rule going forward (user feedback, also saved to auto-memory `template-downstream-sync`): PM commits in downstream repos stage only explicitly template-derived files (never `git add -A`), and pushes to DOWNSTREAM remotes require prior user confirmation. Template-repo (claude-finance) commits/pushes stay routine PM work needing no extra confirmation.
