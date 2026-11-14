# Hybrid OCR Architecture

```text
PDF upload
   |
   v
PyMuPDF triage + Document Inspector (all pages)
   |
   +--> OCR Decision Engine ----> native extraction / existing PaddleOCR
   |                                      |
   +--------------------------------------+
                                          v
                         Document Reconstruction Engine
                                          v
                         Cross-Validation + quality metrics
                                          v
                  Deterministic Fiscal Interpreter
                                          |
                              optional local Ollama
                                          v
                         workspace.json + UI/API traceability
```

The old `core.extract` and `paddle_ocr_engine` remain the extraction source of
truth. New modules add inspection, routing, provenance and validation around
them; they do not install or invoke a second OCR implementation.

## Data flow

1. `document_inspector.inspect_pdf` visits every page and emits a stable report.
2. `ocr_decision_engine.decide_document` maps observed page evidence to a
   processing route.
3. The existing extractor performs native extraction and PaddleOCR recovery.
4. `document_reconstruction` creates page-ordered blocks with source labels.
5. `cross_validation` measures coverage and flags low-confidence OCR/critical
   fields without choosing a semantically convenient value.
6. `fiscal_interpreter` creates a traceable deterministic interpretation. When
   enabled, Ollama receives local blocks only and its result remains a reviewed
   suggestion.
