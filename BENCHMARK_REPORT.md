# Benchmark Report

## Current execution

- Baseline regression before integration: **108 passed, 1 skipped**.
- New hybrid unit tests plus pipeline/triage coverage: **12 passed**.
- Mixed-region OCR, benchmark runner, cancellation and traceability tests:
  **13 passed** in the focused hybrid run.
- Full regression after integration: **118 passed, 1 skipped in 13.45s**.
- Verified native benchmark pilot: **1 case measured, CER 0, WER 0**. PaddleOCR
  was correctly reported as `NOT_RUN` because the case required native text only.
- Real local scanned pilot (synthetic verified reference): **1 case measured**,
  page coverage **100%**, CER **0.025253**, WER **0.296296**, latency **47.4415
  s/page**, peak traced memory **275,819,850 bytes**. Route:
  `SCANNED_IMAGE → PADDLEOCR_FULL_PAGE`.
- Ollama provider verification: **server available locally** at
  `http://localhost:11434`; `qwen2.5:1.5b` was downloaded and detected as an
  installed supported model. A synthetic, non-document JSON generation returned
  the expected result (`tipo=prueba_local`, `resultado=ok`) with **56.641 s**
  first-inference latency. This validates the local provider contract only; it
  is not a fiscal accuracy benchmark.
- Real end-to-end local pipeline with the same synthetic PDF path: Ollama was
  used after reconstruction and validation, with `qwen2.5:1.5b`, one analyzed
  block and **3.792 s** total processing time. The result remained marked for
  human review.
- The legacy `/api/process` path and the asynchronous `/api/process-async`
  path now share `ProcessingPipeline`; the UI exposes local enable/disable and
  supported-model selection through `/api/ollama/config`.
- Reference-corpus CER/WER: **NOT TESTED** — no validated anonymized manifest
  was present in the repository.
- 99% fidelity: **NOT DECLARED** because the specification requires measured
  reference text.

## Runtime fields emitted

Each processed workspace now records page coverage, discrepancy count, critical
field traceability, model/endpoint state, and whether a reference was present.
This keeps operational coverage separate from a true CER/WER fidelity claim.
