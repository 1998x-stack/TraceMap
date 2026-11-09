# API contracts

The original proposed OpenAPI 3.1 contract lives at [1998X Projects / TraceMap technical design](https://github.com/1998x-stack/projects/blob/main/projects/knowledge/llm-xmind/design/contracts/openapi.yaml).

This repository's **implemented API** is exposed by FastAPI at `http://127.0.0.1:8000/openapi.json` and `/docs` in development.

The two are **not yet fully identical**. The development scaffold currently implements the text/PDF path synchronously and an explicitly labelled extractive demo for generation and limited Patch operations. Before G3/G4, reconcile these schemas and add OpenAPI diff CI. Do not mistake the design contract for a production implementation.
