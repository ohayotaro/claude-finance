**Verdict: CHANGES_REQUIRED**

Three blocking findings remain in the delta scope.

1. **High | blocking | new — AC7: Absolute-path case variants bypass the write guard.**  
   [pm-write-guard.py:74](/Users/ohayotaro/claude-finance/.claude/hooks/pm-write-guard.py:74) checks project containment case-sensitively before applying protected-name matching. On this filesystem, `/Users/ohayotaro/CLAUDE-FINANCE/.claude/settings.json` and the normal path identify the same file (`samefile=True`), but the variant returns `Allowed: outside project`. Normalize containment consistently with filesystem identity, and cover case variants in ancestor directories.

2. **Medium | blocking | carried — AC4: Required validation can still disappear silently.**  
   [codex_handoff.py:613](/Users/ohayotaro/claude-finance/.claude/scripts/codex_handoff.py:613) does not recognize fenced commands inside Markdown blockquotes. Under `## Required Validation`, a blockquoted bash fence containing `git diff --check` returns an empty command list; replacing it with a non-allowlisted command also returns an empty list. Consequently, review proceeds without validation evidence or rejection. Parse this formatting or reject it explicitly rather than silently skipping it.

3. **Medium | blocking | new — AC8: Background command separators hide unrelated failures.**  
   [error-to-codex.py:36](/Users/ohayotaro/claude-finance/.claude/hooks/error-to-codex.py:36) splits on `&&` but not standalone `&`. For `pytest -q & python scripts/check.py`, the hook classifies the entire command as validation and returns no advisory even when supplied a Python traceback. Recognize shell command boundaries before exempting the command, with regression coverage for mixed validation and non-validation execution.

**Follow-ups:** None.

**Acceptance-criteria gaps:** AC4, AC7, and AC8 remain unmet as described above. The scoped AC1/AC2 documentation corrections and AC3 lifecycle-scope correction are addressed. No additional AC5/AC6 regression was identified. AC9 was outside this correction scope.

**Validation evidence reviewed:**

- All six runner-required commands exited successfully: 453 tests passed; Ruff, mypy, registry audit, and both Git checks passed.
- Read-only targeted pytest checks passed: **59 passed, 45 deselected**, using `.venv/bin/python -B -m pytest -s -p no:cacheprovider` with the relevant parser, effort, scope, and hook tests selected.
- Read-only Python probes reproduced all three findings.
- Local `git diff --check` passed; the protected gate/settings diff remained empty.
- Initial pytest capture could not create temporary files; disabling capture allowed the targeted tests to run.

**Residual risks:** No trading-runtime changes were reviewed. The guard bypass affects safety-file protection; omitted validation undermines review evidence; hook misclassification suppresses debugging signals. Runner validation still executes repository test code outside the reviewer sandbox, as designed. No repository files were modified or network access enabled.