Status: PASS

Summary: Implemented the unified model/effort tier policy and contract pointer exactly as specified.

Files changed:

- [.claude/rules/codex-delegation.md](/Users/ohayotaro/claude-finance/.claude/rules/codex-delegation.md:33)
- [.claude/docs/CODEX_TASK_CONTRACT.md](/Users/ohayotaro/claude-finance/.claude/docs/CODEX_TASK_CONTRACT.md:146)

Material design decisions:

- Preserved the verbatim policy content unchanged.
- Added only the requested documentation text.
- No runtime, hook, source, or configuration changes.

Validation:

- `git diff --stat`: exactly 2 files, 32 insertions, 0 deletions.
- `grep -n "Model And Effort Tier Policy" ...`: section and pointer found.
- `git diff --check`: passed.
- Added-line non-ASCII check: none found.
- Verbatim block comparison against task brief: identical.
- Section order verified: `Runner (16) < Policy (33) < Failure Handling (63)`.
- No test suite run; documentation-only change.

Acceptance criteria:

- AC1: PASS — section inserted at the required location and byte-identical.
- AC2: PASS — exact pointer added at the end of `Model And Effort`.
- AC3: PASS — only the two target files changed; additions only.
- AC4: PASS — no non-ASCII characters introduced.

Residual risks, debt, or blockers: None.