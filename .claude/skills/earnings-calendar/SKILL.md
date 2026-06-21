---
name: earnings-calendar
description: PM intake for earnings, dividends, corporate actions, and event-driven data tasks.
allowed-tools: "Bash(python3 *) Read Write Edit Glob Grep"
---

# Earnings Calendar

Calendar/data work is T1 for documentation or read-only analysis, T2 for pipeline code, and T3 for external service or production data changes.

## Intake

- Record universe, exchange, date range, event types, data source, and update cadence.
- Define point-in-time availability and revision policy.
- Declare network requirements explicitly if source data is not local.

## Acceptance Checklist

- AC includes event timestamps with timezone and market-session interpretation.
- AC includes corporate action handling and stale/missing data policy.
- AC includes source attribution in generated reports.
- AC includes validation fixtures for known events.

## Delegation

Create the task brief and use the appropriate T1 or T2 flow.
