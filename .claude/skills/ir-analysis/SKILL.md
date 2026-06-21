---
name: ir-analysis
description: Text-only PM intake for investor-relations analysis from provided structured data or extracted text.
allowed-tools: "Bash(python3 *) Read Write Edit Glob Grep"
---

# IR Analysis

This skill accepts only text or structured data already provided by the user or already present in the repository. It does not perform PDF, image, chart, or screenshot extraction.

## Intake

- Record ticker/company, fiscal periods, source text paths, tables, peer set, currency, accounting standard, and user decision need.
- Require source section references for every numeric claim.
- Declare blocker if the only available inputs are PDF/image/chart files that have not been converted to text or structured data.

## Acceptance Checklist

- AC includes bull case, bear case, financial metrics table, forward risks, peer comparison, and confidence.
- AC includes source references for numeric claims.
- AC distinguishes verified facts from inference.
- AC includes no investment advice beyond the requested analytical framing.

## Delegation

For substantial synthesis or code-backed analysis, create a task brief and run T1 or T2 depending on repository mutation.
