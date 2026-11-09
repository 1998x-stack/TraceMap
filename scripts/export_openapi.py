"""Generate a full FastAPI dev contract; check its stable route surface in CI.

    python scripts/export_openapi.py          # snapshot the locally installed version
    python scripts/export_openapi.py --check  # compare route signatures

FastAPI/Pydantic can change generated component schemas between versions. The
CI signature check deliberately compares implemented route metadata rather
than framework-owned definitions. It is NOT a full DTO compatibility test.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps' / 'api'))
os.environ['TRACEMAP_ENV'] = 'development'
os.environ['TRACEMAP_DATABASE_URL'] = 'sqlite://'

from tracemap.main import app  # noqa: E402

HTTP_METHODS = {'get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace'}


def route_signature(spec: dict) -> dict:
    """Stable, reproducible surface; ignores framework component schema churn."""
    signature = {}
    for path, operations in sorted(spec.get('paths', {}).items()):
        for method, operation in sorted(operations.items()):
            if method not in HTTP_METHODS:
                continue
            parameters = sorted(
                (p['in'], p['name'], bool(p.get('required', False)))
                for p in operation.get('parameters', [])
            )
            body = sorted(operation.get('requestBody', {}).get('content', {}).keys())
            statuses = sorted(operation.get('responses', {}).keys())
            signature[f'{method.upper()} {path}'] = {
                'parameters': parameters,
                'requestMediaTypes': body,
                'responseStatuses': statuses,
            }
    return signature


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    destination = ROOT / 'packages' / 'contracts' / 'openapi.generated.json'
    current = app.openapi()
    full_snapshot = json.dumps(current, ensure_ascii=False, sort_keys=True, indent=2) + '\n'
    if args.check:
        if not destination.exists():
            raise SystemExit('OpenAPI snapshot missing. Run: python scripts/export_openapi.py')
        stored = json.loads(destination.read_text())
        if route_signature(stored) != route_signature(current):
            raise SystemExit('Implemented API route signature drift. Run: python scripts/export_openapi.py')
        print(f'OpenAPI route signature OK: {len(route_signature(current))} operations / {len(current["paths"])} paths')
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(full_snapshot)
        print(f'Wrote {destination}: {len(current["paths"])} paths')


if __name__ == '__main__':
    main()
