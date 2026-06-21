---
name: checkpointing
description: Create PM checkpoints and compact task state without changing repository runtime behavior.
allowed-tools: "Read Write Edit Glob Grep"
---

# Checkpointing

Checkpointing is usually T0 or T1. It may write only allowed PM artifact paths such as `.claude/checkpoints/`, `.claude/plans/`, and `.claude/tasks/`.

## Checklist

- Capture current task ID, risk tier, brief path, latest phase artifact, validation status, blockers, and next action.
- Keep secrets and raw credentials out of checkpoint files.
- Link to `brief.md`, `plan.md`, `approval.md`, the `implementation-result` Markdown artifact, `review.md`, and `state.json` instead of duplicating large content.
- If runtime code changes are needed, stop and use `/codex-task`.
