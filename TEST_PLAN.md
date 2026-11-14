# Test Plan — Hybrid Document Intelligence

## Automated coverage

- Digital multipage PDF: every page inspected and native pages preserved.
- Empty/scanned-style pages: recovery/OCR route is explicit.
- Critical token metrics: RFC, amounts, dates/periods and folios are traced.
- CER/WER: exact-match behavior and reference-required policy.
- Deterministic interpretation: page links and human-review requirement.
- Ollama: loopback-only configuration, model discovery and local response shape.
- Existing regression suite: all previous tests must continue to pass.

## Corpus benchmark

Use an anonymized JSONL manifest with one row per reference page:

```json
{"pdf":"digital.pdf","page":1,"text":"texto validado","rfc":"ABC010101XX0","amounts":["100.00"],"dates":["2025"]}
```

Run `runtime\\python.exe hybrid_benchmark.py <manifest.jsonl> --output <report.json>`
and retain the generated report. The runner separates native, PaddleOCR,
hybrid and Ollama stages; unavailable stages remain `NOT_RUN`. Do not claim a
fidelity percentage when the manifest does not contain validated reference text.
