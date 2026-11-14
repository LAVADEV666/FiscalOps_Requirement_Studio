# Test Plan — Hybrid Document Intelligence

## Automated coverage

- Digital multipage PDF: every page inspected and native pages preserved.
- Empty/scanned-style pages: recovery/OCR route is explicit.
- Critical token metrics: RFC, amounts, dates/periods and folios are traced.
- CER/WER: exact-match behavior and reference-required policy.
- Deterministic interpretation: page links and human-review requirement.
- Ollama: loopback-only configuration, model discovery and local response shape.
- Ollama settings API/UI: enable/disable and supported-model selection without
  leaving loopback or changing the PDF source.
- Legacy `/api/process` and asynchronous `/api/process-async`: both must use the
  same hybrid `ProcessingPipeline`.
- Existing regression suite: all previous tests must continue to pass.

## Corpus benchmark

For a non-sensitive routing smoke test, generate the deterministic controlled
corpus (the output is ignored by Git):

```powershell
runtime\python.exe tests\ocr_dataset\generate_controlled_corpus.py tests\ocr_dataset\local\controlled --per-category 10
runtime\python.exe hybrid_benchmark.py tests\ocr_dataset\local\controlled\manifest.jsonl --output tests\ocr_dataset\local\controlled\report.json --pilot
```

The generated references are marked `synthetic_generator`; they prove routing
and instrumentation, not fiscal accuracy. The runner only reports
`promotable=true` when every case is measured, coverage is complete, and both
CER and WER are at or below 1%.

Use an anonymized JSONL manifest with one row per reference page:

```json
{"pdf":"digital.pdf","page":1,"text":"texto validado","rfc":"ABC010101XX0","amounts":["100.00"],"dates":["2025"]}
```

Run `runtime\\python.exe hybrid_benchmark.py <manifest.jsonl> --output <report.json>`
and retain the generated report. The runner separates native, PaddleOCR,
hybrid and Ollama stages; unavailable stages remain `NOT_RUN`. Do not claim a
fidelity percentage when the manifest does not contain validated reference text.
