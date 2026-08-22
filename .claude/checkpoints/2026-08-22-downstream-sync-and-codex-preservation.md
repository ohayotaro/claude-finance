# Checkpoint: downstream sync, .codex incident, and ownership fixes

Date: 2026-08-22 (second checkpoint of the day; continues
2026-08-22-updater-hardening-and-pm-artifact-tracking.md)

## Task: updater-codex-preservation-001

- Risk tier: T2. Status: ACCEPTED, committed `abd5beb`, pushed to main.
- Artifacts: `.claude/tasks/updater-codex-preservation-001/` (brief.md with
  Addenda 1-2, plan.md, approval.md incl. acceptance record,
  implementation-result.md, review.md, state.json).
- Outcome:
  - `.codex` is now a staged file-level overlay (template-managed files
    replaced, project-owned content such as `.codex/plans/` preserved,
    missing template `.codex` is a no-op, fail-closed on special paths).
  - DESIGN.md switched to preserve-local / copy-if-absent (user decision);
    archive machinery removed; legacy `DESIGN.local-preserved*` untouchable.
  - `SELF_UPDATE_PATHS` now includes
    `tests/test_orchestration/test_update_script.py` (user-relayed finding,
    PM-verified: stale downstream updater tests failed against synced
    updaters in all three repos).
- Validation: final review APPROVE (zero findings); PM real-machine
  re-verification: validator PASS, fast suite 215 passed.

## Incident: reactvol-re .codex/plans deletion (resolved)

During the first downstream sync, the then-current wholesale `.codex`
replacement deleted 29 project-owned plan documents in `~/reactvol-re`.
Recovery: 28 tracked files restored from git; 1 untracked file
(`2026-07-13-incumbent-strategy-improvement-plan.md`) reconstructed
byte-for-byte from the authoring Codex session log and committed
(`27b7f41`). Root cause fixed in `abd5beb`. The flaw predated this session
and had been missed by PM and three Codex reviews (fixtures lacked
project-owned `.codex` content); fixtures now cover it.

## Downstream state (all local commits, NOT pushed per user decision)

| Repo | Commits | Notes |
|---|---|---|
| btc-bbo-mm | 31c981c, 72399a0 | .gitignore aligned to template policy; concurrent session active (its own work untouched) |
| reactvol-re | 7c20af7, 27b7f41, d4add8c | own richer PM-artifact gitignore policy retained; 28 plans verified intact through new updater |
| light-blue-cid | 6c19c67 (amended author), 901ea1d | third downstream repo (added this session); concurrent mql5 session active |

All three: on template `abd5beb`, DESIGN.md restored from sync archives
(archives deleted), updater tests 37 passed each. Future syncs are one
updater run (self-update covers scripts, validator, and test; no bootstrap
copying).

## Blockers

None.

## Next actions

1. Downstream pushes: 2-3 local commits per repo await the user's timing
   (downstream pushes require prior confirmation).
2. Backlog, low priority: Codex plan/review artifacts repeatedly delivered
   in Japanese despite the English-artifact rule (three occurrences) --
   candidate runner prompt-template fix.
3. Backlog, non-blocking: fixture for "pre-existing matching DESIGN archive
   while local DESIGN differs" is obsolete after the preserve-local change;
   no action needed unless archives return.
4. Decide fate of any remaining doc references to the removed DESIGN
   archive workflow during the next template doc pass (none known to
   remain).
