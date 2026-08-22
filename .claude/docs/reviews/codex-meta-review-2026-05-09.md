# Meta-Design Review

## TL;DR

The project’s core idea is coherent, but the control surface is not yet self-consistent enough to trust as an orchestrator for trading work.  
The biggest problems are stale architecture docs, skill/tool mismatches that break advertised workflows, and lifecycle rules that claim automation the hooks do not actually provide.  
Routing exists, but it is advisory and ambiguous in exactly the kinds of mixed prompts this repo is meant to handle.

## Critical Issues (must-fix before further use)

- `.claude/docs/DESIGN.md` / `## Specialized Team Agents`  
  Actual contradiction: [`CLAUDE.md`](/Users/ohayotaro/claude-orchestrator/CLAUDE.md:57) routes API bots to `bot-engineer`, and [`ea-developer.md`](/Users/ohayotaro/claude-orchestrator/.claude/agents/ea-developer.md:5) says Python bots should use `bot-engineer`; but [`DESIGN.md`](/Users/ohayotaro/claude-orchestrator/.claude/docs/DESIGN.md:30) assigns “MQL5 EA, Python bots” to `ea-developer`. The same table also omits existing agents `bot-engineer`, `infra-ops`, `ml-engineer`, and `general-purpose` even though they exist in `.claude/agents/` and `routing-keywords.json`.  
  Recommended fix: make `DESIGN.md` the current architecture, not a partial subset; correct `ea-developer` to MQL5-only and list all active agents.

- `.claude/skills/team-implement/SKILL.md` / `## Step 2: Agent Assignment`  
  Coverage gap proven by current files: `bot-develop`, `bot-deploy`, and `ml-pipeline` all tell Claude to transition to `/team-implement` for larger work, but [`team-implement`](/Users/ohayotaro/claude-orchestrator/.claude/skills/team-implement/SKILL.md:21) has no assignment rows for `bot-engineer`, `infra-ops`, or `ml-engineer`.  
  Recommended fix: add those three agents and their scopes, or stop other skills from delegating there.

- `.claude/skills/checkpointing/SKILL.md` vs `.gitignore`  
  Resolution (2026-08-22): Resolved. The finding below records historical state; `.claude/checkpoints/` is now tracked in Git.
  Actual contradiction: [`checkpointing`](/Users/ohayotaro/claude-orchestrator/.claude/skills/checkpointing/SKILL.md:111) says to `git add CLAUDE.md .claude/checkpoints/ ...` and commit checkpoints, but [`.gitignore`](/Users/ohayotaro/claude-orchestrator/.gitignore:32) ignores `.claude/checkpoints/`.  
  Recommended fix: either unignore `.claude/checkpoints/` or change the skill to local-only checkpoints with no git commit step.

- Multiple skills / tool permissions  
  Actual workflow breakage:
  - [`backtest`](/Users/ohayotaro/claude-orchestrator/.claude/skills/backtest/SKILL.md:5) lacks `Bash(gemini *)` but Step 8 calls Gemini.
  - [`incident-response`](/Users/ohayotaro/claude-orchestrator/.claude/skills/incident-response/SKILL.md:4) lacks `Bash(systemctl *)` but uses `systemctl`.
  - [`bot-deploy`](/Users/ohayotaro/claude-orchestrator/.claude/skills/bot-deploy/SKILL.md:6) lacks `Bash(curl *)` but uses `curl`.
  - [`team-implement`](/Users/ohayotaro/claude-orchestrator/.claude/skills/team-implement/SKILL.md:4) lacks `Bash(mypy *)` but requires `mypy`.
  - [`dashboard-develop`](/Users/ohayotaro/claude-orchestrator/.claude/skills/dashboard-develop/SKILL.md:4) allows `npm`/`npx`, but [`.claude/settings.json`](/Users/ohayotaro/claude-orchestrator/.claude/settings.json:3) does not.  
  Recommended fix: align each skill’s `allowed-tools` and the harness permission list with the commands the workflow actually uses.

- `.claude/hooks/agent-router.py` / priority model  
  Actual contradiction between docs and code: the header says priority is Gemini > Codex > specialized subagent, but the implementation only appends all matches; it never chooses one route. For `find the bug in this 200-line backtest`, current routing likely suggests `general-purpose` (`find`) and `quant-analyst` (`backtest`), but misses `codex-debugger` because `bug` is not in its keywords and `bug` is not in the Codex keyword list either.  
  Recommended fix: pick one primary route, add debugger keywords like `bug`, `failing test`, `regression`, and use fallback suggestions only when scores are close.

## High-Priority Improvements (ranked, with rationale)

1. Normalize Codex prompt ownership.  
   The same template family is duplicated in [`codex-delegation.md`](/Users/ohayotaro/claude-orchestrator/.claude/rules/codex-delegation.md:30), [`CODEX_HANDOFF_PLAYBOOK.md`](/Users/ohayotaro/claude-orchestrator/.claude/docs/CODEX_HANDOFF_PLAYBOOK.md:1), [`codex-system/SKILL.md`](/Users/ohayotaro/claude-orchestrator/.claude/skills/codex-system/SKILL.md:16), and many individual skills. This is the highest drift surface in the repo. Canonical source should be `CODEX_HANDOFF_PLAYBOOK.md`; other files should point to named templates, not restate them.

2. Downgrade “automatic” document lifecycle language or actually wire it into hooks.  
   [`document-lifecycle.md`](/Users/ohayotaro/claude-orchestrator/.claude/rules/document-lifecycle.md:74) claims update points are “enforced by skill workflows and orchestrator awareness”, but no hook updates `CLAUDE.md`, `DESIGN.md`, `CODEX_HANDOFF_PLAYBOOK.md`, incidents, or checkpoints. Today this is mostly manual discipline plus reminders. The doc should say that clearly unless you add real enforcement.

3. Fix the current playbook gap the lifecycle rule already defines.  
   [`document-lifecycle.md`](/Users/ohayotaro/claude-orchestrator/.claude/rules/document-lifecycle.md:123) says each Codex-using skill should have a corresponding handoff template, but the current playbook has only six generic sections. Missing patterns include `team-review`, `incident-response`, `ir-analysis`, `equity-screener`, `sector-analysis`, `optimize`, and `ml-pipeline`.

4. Clarify direct implementation policy.  
   [`CLAUDE.md`](/Users/ohayotaro/claude-orchestrator/CLAUDE.md:8) says Claude “does NOT implement directly,” but agentless skills like [`strategy-design`](/Users/ohayotaro/claude-orchestrator/.claude/skills/strategy-design/SKILL.md:83) and [`dashboard-develop`](/Users/ohayotaro/claude-orchestrator/.claude/skills/dashboard-develop/SKILL.md:98) instruct direct file creation. This is at least an ambiguity, and likely a contradiction unless `agent:` frontmatter semantics cover it.

5. Tighten live-trading safety gates around existing rules.  
   The repo has strong written rules for testnet-first and mandatory risk controls in [`security.md`](/Users/ohayotaro/claude-orchestrator/.claude/rules/security.md:38), [`bot-development.md`](/Users/ohayotaro/claude-orchestrator/.claude/rules/bot-development.md:216), and [`risk-management.md`](/Users/ohayotaro/claude-orchestrator/.claude/rules/risk-management.md:3), but nothing in hooks/settings blocks a “live” path when those checks were skipped. For a trading orchestrator, this is the main practical failure mode.

## Medium / Low Priority Improvements

- `routing-keywords.json` and `.claude/agents/` are currently in sync; no orphaned or missing routing keys found. The problem is routing quality, not routing-key existence.
- [`init-finance`](/Users/ohayotaro/claude-orchestrator/.claude/skills/init-finance/SKILL.md:44) still says to ignore `uv.lock`, which conflicts with [`coding-principles.md`](/Users/ohayotaro/claude-orchestrator/.claude/rules/coding-principles.md:76) and the current repo state. This is drift, not a structural failure.
- Lifecycle paths the docs rely on are absent right now: `.claude/checkpoints/`, `.claude/docs/incidents/`, `.claude/logs/agent-teams/`, `src/data/api_specs/`, and `tests/test_strategies/`. That is acceptable if they are created on first use, but the docs should stop sounding like they are always present.
- [`incident-response`](/Users/ohayotaro/claude-orchestrator/.claude/skills/incident-response/SKILL.md:42) assumes synchronous callable `src.bot.executor` emergency functions, while [`bot-engineer.md`](/Users/ohayotaro/claude-orchestrator/.claude/agents/bot-engineer.md:13) defines an async architecture. That recovery path is under-specified and likely wrong in real bot code.
- Logging/monitoring contract details are duplicated across [`bot-development.md`](/Users/ohayotaro/claude-orchestrator/.claude/rules/bot-development.md:72), [`monitoring.md`](/Users/ohayotaro/claude-orchestrator/.claude/rules/monitoring.md:31), [`bot-develop`](/Users/ohayotaro/claude-orchestrator/.claude/skills/bot-develop/SKILL.md:87), [`bot-monitor`](/Users/ohayotaro/claude-orchestrator/.claude/skills/bot-monitor/SKILL.md:22), and [`notification-setup`](/Users/ohayotaro/claude-orchestrator/.claude/skills/notification-setup/SKILL.md:11). Canonical location should be `bot-development.md`; the others should reference it.

## Specific Concrete Edits

- `.claude/docs/DESIGN.md:25` → change the agent table to list all nine current agents and change `ea-developer` from “MQL5 EA, Python bots” to “MQL5 EA”.  
  Justification: fixes a live contradiction with `CLAUDE.md` and `ea-developer.md`.

- `.claude/skills/team-implement/SKILL.md:21` → add rows for `bot-engineer`, `infra-ops`, and `ml-engineer`, with file scopes matching the rest of the repo.  
  Justification: other skills already depend on `/team-implement` for those domains.

- `.gitignore:32` → remove `.claude/checkpoints/` from ignore, or `.claude/skills/checkpointing/SKILL.md:111` → remove the commit step and describe checkpoints as local-only.  
  Justification: current state cannot satisfy both files.
  Resolution (2026-08-22): The first option was implemented; this recommendation is retained as historical review evidence.

- `.claude/skills/backtest/SKILL.md:5` → add `Bash(gemini *)` to `allowed-tools`, or delete Step 8.  
  Justification: the current skill advertises an optional Gemini phase it cannot execute.

- `.claude/skills/incident-response/SKILL.md:4` → add `Bash(systemctl *)`, or replace `systemctl` paths with Docker-only instructions.  
  Justification: current emergency stop procedure includes commands the skill disallows.

- `.claude/skills/bot-deploy/SKILL.md:6` → add `Bash(curl *)`, or rewrite verification to use an allowed Python HTTP check.  
  Justification: Step 7 currently calls an unavailable tool.

- `.claude/skills/team-implement/SKILL.md:4` → add `Bash(mypy *)`.  
  Justification: Steps 4 and 6 require `mypy`.

- `.claude/skills/dashboard-develop/SKILL.md:4` or `.claude/settings.json:3` → align `npm`/`npx` support in one direction.  
  Justification: dashboard workflow currently claims JS toolchains that the harness does not permit.

- `.claude/hooks/agent-router.py:100` → change “append all matching suggestions” to “select one primary route plus optional fallback”, and add debugger terms including `bug`, `failing test`, and `regression`.  
  Justification: current router does not enforce its stated priority and misroutes common bug prompts.

- `.claude/hooks/post-backtest-analysis.py:80` → check `exit_code` before emitting “BACKTEST COMPLETED”; on failure, emit a failure context instead.  
  Justification: the hook currently reports completion based only on keyword match.

- `.claude/hooks/post-implementation-review.py:63` → count diff/additions, not full replacement content on every edit.  
  Justification: repeated edits to the same file inflate line totals and trigger noisy reviews.

- `.claude/skills/init-finance/SKILL.md:44` → remove `uv.lock` from the generated `.gitignore` template.  
  Justification: it conflicts with `coding-principles.md` and the tracked repo pattern.

## Open Questions for the User

- Does `agent:` in skill frontmatter mean the whole skill executes in that subagent context, or is the main orchestrator still expected to perform the file edits? This determines whether the “does NOT implement directly” language is truly contradictory.
- Do you want checkpoints committed to git, or only stored locally for session recovery?
- Is `dashboard-develop` intentionally meant to support Vite/JS workflows, or should this orchestrator stay Python-only?
- Should routing prefer “best single agent” or “show several suggestions and let Claude decide”? The current docs say the former, the hook behaves like the latter.

## Confidence

- **Internal consistency:** High. I read the key policy docs, all rules, all agents, routing, settings, and hooks; the contradictions above are direct file-to-file conflicts.
- **Coverage gaps:** High. The missing `/team-implement` coverage, playbook gaps, and absent lifecycle paths are directly observable in the repo.
- **Routing clarity:** High. `agent-router.py` is short and deterministic; the ambiguity comes from its current matching strategy and keyword set.
- **Document lifecycle realism:** High. I found no hook that updates the claimed documents; the current mechanism is mostly textual process.
- **Practical effectiveness for financial trading:** Medium. The missing enforcement before live-trading actions is clear, but confidence would be higher if I also reviewed the intended operational repo that this orchestrator controls.
- **Hook reliability:** Medium-High. I reviewed all hook source, but confidence would be higher with actual Claude hook event payload samples and a live run confirming tool schema assumptions.
