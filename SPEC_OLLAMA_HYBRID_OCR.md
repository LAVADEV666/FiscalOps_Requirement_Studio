# Specification — Ollama + Hybrid OCR

## Objective

Add local-only document intelligence to the existing FiscalOps Requirement
Studio pipeline while preserving the native PDF extraction, PaddleOCR,
human-review and workspace contracts already in use.

## Invariants

- The source PDF is never modified.
- Text is not sent to cloud services.
- Ollama is optional and disabled by default.
- Critical values are not completed or corrected by an LLM.
- Every inspected page has a classification and processing status.
- Fidelity percentages are only calculated when a validated reference exists.

## Contracts

- `document_inspection.json`: page dimensions, orientation, native text,
  images, tables, graphics, quality signals and classification.
- `ocr_decisions.json`: deterministic OCR route and source priority per page.
- `reconstruction`: canonical page-ordered text and block-level provenance.
- `cross_validation`: critical tokens, discrepancies, coverage and review state.
- `fiscal_interpretation`: deterministic interpretation plus optional Ollama
  block outputs, always marked for human review.
- OCR diagnostics retain every attempted preprocessing profile and the selected
  profile, including confidence, block count and character coverage.

## Supported local models

`qwen3.5:4b` is the recommended local model for semantic boundary detection,
with `gemma3:4b` as an alternative. The compatibility set also includes
`qwen2.5:3b`, `qwen2.5:1.5b`, `llama3.2:3b`, `qwen3.5:9b` and
`qwen2.5-coder:7b`. Model availability is detected at runtime; no model is
assumed to be installed.

## Semantic request boundaries

After native extraction or OCR, `boundary_analyzer` creates conservative
candidates from authority request language and explicit `Punto N` anchors.
Numbers inside reproduced taxpayer statements are treated as document data,
not as requirements. When Ollama is enabled, it receives compact windows with
stable page-line identifiers and returns candidate start/end lines. The result
is accepted only if every line exists, boundaries are ordered, the requested
Punto is present, and the model stays within the deterministic safe envelope.
Otherwise the deterministic candidate is retained and marked for review.
