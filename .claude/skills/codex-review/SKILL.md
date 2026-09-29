---
name: codex-review
description: Run an explicit fresh Codex review for the current task, result artifact, repository, and diff.
allowed-tools: "Bash(python3 *) Read Write Edit Glob Grep"
---

# Codex Review

Use this when the user asks for an independent review or when a T2/T3 task is implemented and validated.

## Preconditions

- `.claude/tasks/<task-id>/brief.md` exists and states the current spec.
- `implementation-result.md` exists and lists changed files plus exact validation commands and results.
- For a delta review, `review-scope.md` lists the blocking findings addressed and the files touched.
- The reviewer never receives the implementation transcript.

## Run

```bash
uv run python .claude/scripts/codex_handoff.py review <task-id>
uv run python .claude/scripts/codex_handoff.py review <task-id> --scope delta
```

The runner moves an existing `review.md` to `review-<n>.md` before the new review starts.

## Acceptance Use

Each finding has a severity (`Critical`, `High`, `Medium`, `Low`), a disposition (`blocking` or `follow-up`), and an origin (`new`, or `carried` from the previous round). A finding is blocking if and only if it is Critical or High, directly violates a stated acceptance criterion, is a failing required validation command, or weakens a financial safeguard. The verdict is `CHANGES_REQUIRED` if and only if at least one blocking finding exists; otherwise `APPROVE`. Record follow-ups in `acceptance.md` and decide per item whether to fix now or track. After the third `CHANGES_REQUIRED` verdict in one task, stop and report the cycle history and options to the user.
