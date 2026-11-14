# Implementation Plan

| Phase | Scope | Status |
|---|---|---|
| 0 | Audit current PDF/OCR/workspace/UI flow | DONE |
| 1 | Local Ollama configuration, health, model list, retries and cancellation contract | DONE |
| 2 | Full-page Document Inspector and page classification | DONE |
| 3 | Deterministic OCR Decision Engine | DONE |
| 4 | Preserve and route through existing PaddleOCR | DONE — full-page routes and image-region OCR for mixed pages use the existing engine |
| 5 | Page-ordered reconstruction and provenance | DONE |
| 6 | Cross-validation and quality metrics | DONE |
| 7 | Fiscal interpretation after validation | DONE — deterministic first; Ollama optional and reviewed |
| 8 | Compact API/UI status integration | PARTIAL — status card and APIs are integrated; full side-by-side discrepancy viewer remains |
| 9 | Benchmark, regression and stabilization | PARTIAL — reproducible runner and regression suite added; real corpus/model execution awaits reference manifest and local model |

## Known boundaries

The application cannot claim 99% fidelity without a validated reference set.
Mixed pages are classified and receive a native-plus-regions decision. Embedded
visual regions are OCRed through the existing PaddleOCR engine when it is
available; the existing UI OCR-zone workflow remains available for regions that
are not represented as embedded images or require human selection.
