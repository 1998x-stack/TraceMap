# API contracts / 接口契约

Two *distinct* specifications are maintained intentionally:

1. [`openapi.generated.json`](openapi.generated.json) is **generated from actual local FastAPI routes** (v0.3 development implementation). It covers 19 path templates. CI checks drift on each push/PR:

   ```bash
   python scripts/export_openapi.py --check
   # after intentional route/schema changes:
   python scripts/export_openapi.py
   ```

2. The [future product OpenAPI 3.1 design](https://github.com/1998x-stack/projects/blob/main/projects/knowledge/llm-xmind/design/contracts/openapi.yaml) describes intended behavior. It is **not** a live server guarantee: real LLM/worker, production auth, and full Patch operations remain unavailable.

**Important:** Many prototype response types are currently inferred or untyped in FastAPI. This generated snapshot is a useful path/parameter/validation drift gate, **not** a complete DTO equivalence proof. Full typed responses, client generation and schema-level contract testing are follow-up work.
