# Implementation Plan

| Phase | Scope | Status |
|---|---|---|
| 0 | Audit current PDF/OCR/workspace/UI flow | DONE |
| 1 | Local Ollama configuration, health, model list, retries and cancellation contract | DONE |
| 2 | Full-page Document Inspector and page classification | DONE |
| 3 | Deterministic OCR Decision Engine | DONE |
| 4 | Preserve and route through existing PaddleOCR | PARTIAL — full-page routes are integrated; mixed-page regions remain explicit review work |
| 5 | Page-ordered reconstruction and provenance | DONE |
| 6 | Cross-validation and quality metrics | DONE |
| 7 | Fiscal interpretation after validation | DONE — deterministic first; Ollama optional and reviewed |
| 8 | Compact API/UI status integration | PARTIAL — status card and APIs are integrated; full side-by-side discrepancy viewer remains |
| 9 | Benchmark, regression and stabilization | PARTIAL — regression suite and unit coverage added; real corpus benchmark awaits reference manifest |

## Known boundaries

The application cannot claim 99% fidelity without a validated reference set.
Mixed pages are classified and receive a native-plus-regions decision, but the
existing UI's OCR-zone workflow remains the safe mechanism for selecting those
regions rather than running a second full-page OCR pass.
