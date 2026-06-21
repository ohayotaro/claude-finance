# Document Lifecycle Rules

All persistent documents in this project have defined update triggers. No document should become stale without an explicit decision to archive or remove it.

## Document Registry

### CLAUDE.md

| Zone | Update Trigger | Responsible | Method |
|------|---------------|-------------|--------|
| **Zone A** (template rules) | Template version upgrade only | Template maintainer | Manual or `Section 9.2` update procedure |
| **Zone B** (project identity) | `/init-finance` (initial), or when project scope changes (new market, new data source, new platform) | User or orchestrator | Edit Zone B directly. Must update when: new exchange added, tech stack changed, key commands changed |
| **Zone C** (working context) | Every significant decision, architecture change, or strategy addition | Orchestrator | Append. Triggers: (1) `/strategy-design` completes, (2) `/bot-develop` architecture finalized, (3) major refactor, (4) `/checkpointing` |

**Zone C staleness rule**: If Zone C exceeds 50 lines, the orchestrator should summarize and trim older entries on next `/checkpointing` call.

### .claude/docs/DESIGN.md

| Event | Action |
|-------|--------|
| New skill/module added | Add architecture decision record (ADR) when architecture changes |
| Architecture pattern changed | Update relevant ADR |
| `/strategy-design` produces new architecture | Append strategy architecture summary |
| `/bot-develop` finalizes bot architecture | Append bot component diagram |
| `/codex-review` identifies architecture issues | Update with resolution |

**Ownership**: Orchestrator updates after any structural change. Codex reviews for consistency.

### .claude/docs/CODEX_TASK_CONTRACT.md

| Event | Action |
|-------|--------|
| Task brief schema changes | Update the canonical schema |
| Phase output contract changes | Update plan, implementation, or review output requirements |
| Runner behavior changes | Update runner usage and guarantees |

**Ownership**: Updated when the Claude PM to Codex engineering contract changes.

### MEMORY.md (Claude Code auto memory)

This file is managed by Claude Code's auto memory system. Project-specific guidance:

| What to save | What NOT to save |
|---|---|
| User preferences for analysis style | Code patterns (derive from code) |
| Non-obvious project constraints | Git history (use git log) |
| Validated approach decisions | Ephemeral task state |
| External resource locations | Anything in CLAUDE.md or DESIGN.md |

**Rule**: Do not duplicate information that exists in CLAUDE.md Zone B/C or DESIGN.md.

### reports/ (Backtest)

| Document | Created by | Retention |
|----------|-----------|-----------|
| `reports/backtest_*.html` | `/backtest` | Keep all. Compare across strategy versions |

### .claude/docs/incidents/

| Document | Created by | Retention |
|----------|-----------|-----------|
| `incidents/{date}_{title}.md` | `/incident-response` | Keep all. Postmortems are permanent records |

### src/data/api_specs/

| Document | Created by | Update Trigger |
|----------|-----------|---------------|
| `api_specs/{source}.md` | `/data-pipeline` Step 2, `/bot-develop` Step 2 | When API version changes, endpoint deprecation, or rate limit change detected |

**Staleness check**: Before implementing against an existing api_spec, verify the documented API version matches the current version. If >6 months old, re-research.

## Update Points (manual)

> **Honest scope**: There is no hook that automatically writes to CLAUDE.md, DESIGN.md, CODEX_HANDOFF_PLAYBOOK.md, or `incidents/` when these events fire. Enforcement is by orchestrator discipline, reinforced by `/checkpointing` Step 7 (Drift Detection). The list below is a contract Claude follows, not an automation guarantee — if a skill below completes without the corresponding update, that is a drift.

These events SHOULD trigger document updates (manually, by the orchestrator running the skill):

```
/init-finance          → CLAUDE.md Zone B (create)
/strategy-design       → CLAUDE.md Zone C (append), DESIGN.md (ADR if new pattern)
/bot-develop           → CLAUDE.md Zone C (append), DESIGN.md (bot architecture)
/backtest              → reports/ (create)
/optimize              → reports/ (create), CLAUDE.md Zone C (best params)
/ea-generate           → DESIGN.md (EA architecture)
/incident-response     → .claude/docs/incidents/ (create)
/checkpointing         → CLAUDE.md Zone C (summarize + trim)
/data-pipeline Step 2  → src/data/api_specs/ (create or update)
/bot-develop Step 2    → src/data/api_specs/ (create or update)
```

## Drift Detection

The orchestrator checks the following conditions on `/checkpointing` or session start. Each condition describes a concrete state where a document no longer reflects reality.

### 1. CLAUDE.md Zone C — Context Overload

**Condition**: Zone C exceeds 50 lines.

**Problem**: Old investigation notes, rejected approaches, and current decisions are intermixed. The orchestrator may treat a discarded idea as an active constraint.

**Action**: Summarize older entries into a 5-line digest. Remove entries for work that is already committed and reflected in code.

### 2. DESIGN.md — Code/Document Divergence

**Condition**: `git log --since="$(stat -f %Sm -t %Y-%m-%d .claude/docs/DESIGN.md)" --oneline -- src/ mql5/` returns commits that add, rename, or remove modules not reflected in DESIGN.md.

**Problem**: A new module exists in code but has no architecture decision record. Or DESIGN.md describes a module that was deleted or renamed.

**Action**: For each divergence, either (a) add an ADR for the new module, or (b) remove/update the stale ADR. Flag to user with the specific file mismatches.

### 3. api_specs/ — Endpoint/Version Mismatch

**Condition**: The `## Base URL` or `## Endpoints Used` section in an api_spec document does not match the URLs/paths used in the corresponding Python client code (`grep -r "base_url\|endpoint\|/api/v" src/data/ src/bot/`).

**Problem**: The exchange updated their API (version bump, endpoint deprecation, new rate limits), but the spec was not re-researched. Implementation may use deprecated endpoints or violate new rate limits.

**Action**: Re-run the API specification research from official docs. If network access is required, record it in the task brief and obtain explicit handling before implementation. Update the spec and verify client code matches.

**Secondary check**: If the spec file's last-modified date is >6 months old AND the code references it, flag for verification regardless.

### 4. CODEX_TASK_CONTRACT.md — Contract Drift

**Condition**: A skill describes a task flow or phase output that does not match `.claude/docs/CODEX_TASK_CONTRACT.md`.

**Problem**: Claude PM artifacts and Codex phase outputs can drift, reducing auditability.

**Action**: Update the skill or the canonical contract so the risk-tier flow, task brief schema, and phase output requirements agree.

### 5. Skill and Runner Drift

**Condition**: A skill embeds large handoff prompts or direct Codex flag templates instead of invoking `.claude/scripts/codex_handoff.py`.

**Problem**: Delegation becomes non-deterministic and hard to audit.

**Action**: Convert the skill to a thin PM intake checklist that references the canonical task contract and central runner.
