---
name: incident-response
description: PM workflow for trading incidents, emergency evidence capture, and Codex root-cause tasks.
allowed-tools: "Bash(python3 *) Read Write Edit Glob Grep"
---

# Incident Response

Incident response is T3 when live trading, credentials, deployment, or external side effects are involved.

## First Actions

- If a live bot is unsafe, use the existing kill switch and manual operational procedures. Do not ask Codex to execute live trades.
- Capture severity, strategy_id, first detected UTC time, impacted venue/account, observed symptom, actions already taken, and current safety state.
- Preserve logs, recent trades, config snapshots, and health/risk evidence without secrets.

## Acceptance Checklist

- AC includes timeline reconstruction in UTC.
- AC includes verified root cause versus alternatives.
- AC includes immediate remediation, permanent fix proposal, and regression test.
- AC includes risk of re-enabling and explicit operator approval gate.
- AC includes postmortem artifact under approved PM paths.

## Delegation

Create a T3 task brief. Run `plan`, obtain Claude and explicit user approval for any implementation or external action, then run `implement` and `review`.
