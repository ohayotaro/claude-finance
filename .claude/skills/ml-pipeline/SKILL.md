---
name: ml-pipeline
description: PM intake for financial ML features, training, validation, and production-readiness tasks.
allowed-tools: "Bash(python3 *) Read Write Edit Glob Grep"
---

# ML Pipeline

Financial ML implementation is T2 by default and T3 if it changes live inference, deployment, credentials, or production data.

## Intake

- Record target, horizon, feature list, labels, train/validation/test dates, purge/embargo, model family, metrics, and retraining cadence.
- Define point-in-time feature availability and label isolation.
- Identify required data sources and whether network or production data is needed.

## Acceptance Checklist

- AC includes leakage audit for every feature.
- AC includes purge/embargo and walk-forward validation.
- AC includes train/test drift checks and overfitting assessment.
- AC includes feature importance sanity review and ablation where relevant.
- AC includes regression tests or reusable evaluation scripts.

## Delegation

Create the task brief and run the T2 flow. Live inference/deployment requires T3 approval.
