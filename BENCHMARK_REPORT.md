# Benchmark Report

## Current execution

- Baseline regression before integration: **108 passed, 1 skipped**.
- New hybrid unit tests plus pipeline/triage coverage: **12 passed**.
- Mixed-region OCR, benchmark runner and cancellation tests: **12 passed**.
- Full regression after integration: **115 passed, 1 skipped in 12.68s**.
- Verified native benchmark pilot: **1 case measured, CER 0, WER 0**. PaddleOCR
  was correctly reported as `NOT_RUN` because the case required native text only.
- Real local scanned pilot (synthetic verified reference): **1 case measured**,
  page coverage **100%**, CER **0.025253**, WER **0.296296**, latency **47.4415
  s/page**, peak traced memory **275,819,850 bytes**. Route:
  `SCANNED_IMAGE → PADDLEOCR_FULL_PAGE`.
- Ollama provider verification: **server available** at `http://localhost:11434`;
  installed models were `gemma3:4b`, `qwen3.5:9b`, `qwen2.5-coder:7b` and
  `qwen3.5:4b`. The three configured FiscalOps models were not installed, so
  model inference remains `NOT_RUN`.
- Reference-corpus CER/WER: **NOT TESTED** — no validated anonymized manifest
  was present in the repository.
- 99% fidelity: **NOT DECLARED** because the specification requires measured
  reference text.

## Runtime fields emitted

Each processed workspace now records page coverage, discrepancy count, critical
field traceability, model/endpoint state, and whether a reference was present.
This keeps operational coverage separate from a true CER/WER fidelity claim.
