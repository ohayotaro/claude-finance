# harness-convergence-001: Approvals and decision history

## User decisions (2026-09-29)

- Operating model: Claude implementation + Codex review (chosen over "keep Codex implementation, lighten the harness" and "Codex for T3 only").
- `pm-write-guard.py` rewrite to protect only safety-gate files and credentials: explicitly approved.
- Review validation: runner executes allowlisted validation commands before the review; the review sandbox stays read-only (chosen over a writable review sandbox).
- `pm-write-guard.py` symlink fix (review round 1, finding 4): explicitly approved.
- Codex effort levels `max` and `ultra` are not adopted.

## Superseded

- Brief Revision 1 (Codex plan -> approval -> Codex implementation of eight harness items, including a writable review sandbox and implement-session continuity) was superseded by Revision 2 after the user switched the operating model. The Revision 1 Codex plan run was cancelled before producing output.
