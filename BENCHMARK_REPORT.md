# Benchmark Report

## Current execution

- Baseline regression before integration: **108 passed, 1 skipped**.
- New hybrid unit tests plus pipeline/triage coverage: **12 passed**.
- Full regression after integration: **112 passed, 1 skipped in 12.18s**.
- Reference-corpus CER/WER: **NOT TESTED** — no validated anonymized manifest
  was present in the repository.
- 99% fidelity: **NOT DECLARED** because the specification requires measured
  reference text.

## Runtime fields emitted

Each processed workspace now records page coverage, discrepancy count, critical
field traceability, model/endpoint state, and whether a reference was present.
This keeps operational coverage separate from a true CER/WER fidelity claim.
