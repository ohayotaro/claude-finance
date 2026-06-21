---
name: data-pipeline
description: PM intake for market data ingestion, normalization, storage, and quality validation.
allowed-tools: "Bash(python3 *) Read Write Edit Glob Grep"
---

# Data Pipeline

Data pipeline work is T2 by default and T3 if it mutates production data stores, credentials, schemas, or external services.

## Intake

- Record market, symbols, venue, timeframe, historical range, source API, adjusted/raw price policy, and storage format.
- Require official API docs before client implementation. If network is needed, declare `Network access: required` in the brief and stop until explicitly handled.
- Define point-in-time requirements, timezone normalization, retry behavior, rate limits, and idempotency.

## Acceptance Checklist

- AC includes UTC or explicit exchange timezone handling.
- AC includes schema validation, missing-value policy, duplicate handling, and data-quality report.
- AC includes no look-ahead corrections during historical reconstruction.
- AC includes reusable validation script and tests with fixtures.
- AC includes Parquet for large data and CSV only for small interchange files.

## Delegation

Create the task brief and run the T2 flow. Schema or destructive data migration requires T3 approval.
