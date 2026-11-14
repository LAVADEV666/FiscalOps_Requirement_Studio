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

`qwen2.5:3b`, `qwen2.5:1.5b` and `llama3.2:3b`. Model availability is
detected at runtime; no model is assumed to be installed.
