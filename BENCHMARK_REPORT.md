# Benchmark Report

## Current execution

- Baseline regression before integration: **108 passed, 1 skipped**.
- New hybrid unit tests plus pipeline/triage coverage: **12 passed**.
- Mixed-region OCR, benchmark runner, cancellation and traceability tests:
  **13 passed** in the focused hybrid run.
- Full regression after integration: **123 passed, 1 skipped in 16.49s**.
- Verified native benchmark pilot: **1 case measured, CER 0, WER 0**. PaddleOCR
  was correctly reported as `NOT_RUN` because the case required native text only.
- Real local scanned pilot (synthetic verified reference): **1 case measured**,
  page coverage **100%**, CER **0.004082**, WER **0.032258**, latency **70.8151
  s/page**, peak traced memory **408,416,859 bytes**. Route:
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
  **100% page coverage**, CER **0.019322**, WER **0.141035**, **5.7967 s/case**
  and **408,501,465 bytes** peak traced memory. The mixed case used route
  `NATIVE_PLUS_REGIONS`, mode `mixed_regions`, CER **0.000000** and WER
  **0.000000**. Category CER was digital **0.000000**, scanned-good
  **0.004082**, scanned-regular **0.036693** and scanned-bad **0.030738**. The corrected 99% quality gates
  returned `promotable=false` because CER and WER remain above 1%; no fidelity
  claim is made for this synthetic corpus.
- OCR resolution comparison on the same scanned case: `400 DPI` improved WER
  to `0.032258` versus `0.064516` at 2048-side detection with 300 DPI input.
  The default is configurable through `FISCALOPS_OCR_RENDER_DPI`, bounded by a
  page pixel budget, while `FISCALOPS_OCR_DET_LIMIT_SIDE_LEN` remains bounded
  to `1024..4096`.
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
