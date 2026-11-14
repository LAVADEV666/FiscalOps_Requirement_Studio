# Benchmark Report

## Current execution

- Baseline regression before integration: **108 passed, 1 skipped**.
- New hybrid unit tests plus pipeline/triage coverage: **12 passed**.
- Mixed-region OCR, benchmark runner, cancellation and traceability tests:
  **13 passed** in the focused hybrid run.
- Full regression after integration: **120 passed, 1 skipped in 14.65s**.
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
- Reproducible benchmark runner with Ollama enabled: **1 verified synthetic
  case**, Ollama stage `RUN`, one case analyzed, **2.514 s** model latency and
  `promotable=true`. The OCR stage was correctly kept separate because the case
  contained verified native text.
- Controlled synthetic corpus generated locally: **43 verified pages** (10
  digital, 10 scanned-good, 10 scanned-regular, 10 scanned-bad, one mixed and
  two multipage references). Real PaddleOCR execution covered all pages with
  **100% page coverage**, CER **0.229008**, WER **0.182414**, **3.239 s/case**
  and **277,404,490 bytes** peak traced memory. The mixed case used route
  `NATIVE_PLUS_REGIONS`, mode `mixed_regions`, CER **0.235669**. Category CER
  was digital **0.000000**, scanned-good **0.633878**, scanned-regular
  **0.066129** and scanned-bad **0.249590**. The corrected 99% quality gates
  returned `promotable=false`; no fidelity claim is made for this synthetic
  corpus.
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
