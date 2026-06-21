---
name: codex-review
description: Run an explicit fresh Codex review for the current task, result artifact, repository, and diff.
allowed-tools: "Bash(python3 *) Read Write Edit Glob Grep"
---

# Codex Review

Use this when the user asks for an independent review or when a T2/T3 task reaches the review phase.

## Preconditions

- `.claude/tasks/<task-id>/brief.md` exists.
- `plan.md` exists for T2/T3.
- The `implementation-result` Markdown artifact exists and summarizes changed files plus validation evidence.
- The reviewer must not receive the implementation transcript.

## Run

```bash
python3 .claude/scripts/codex_handoff.py review <task-id>
```

## Acceptance Use

Claude compares `review.md` against the brief, plan, the `implementation-result` Markdown artifact, test evidence, and user intent. Any `CHANGES_REQUIRED` verdict or unresolved high-severity financial, operational, security, or regression risk blocks acceptance unless the brief is explicitly revised.
