"""Generate/check the exact FastAPI development contract without starting a server.

    python scripts/export_openapi.py          # write version-controlled snapshot
    python scripts/export_openapi.py --check  # fail on drift in CI

This reflects implemented development routes. It is *not* the proposed
production contract from projects/.../design/contracts/openapi.yaml.
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    destination = ROOT / 'packages' / 'contracts' / 'openapi.generated.json'
    snapshot = json.dumps(app.openapi(), ensure_ascii=False, sort_keys=True, indent=2) + '\n'
    if args.check:
        if not destination.exists() or destination.read_text() != snapshot:
            raise SystemExit('OpenAPI contract drift. Run: python scripts/export_openapi.py')
        print(f'OpenAPI contract OK: {len(app.openapi()["paths"])} paths')
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(snapshot)
        print(f'Wrote {destination}: {len(app.openapi()["paths"])} paths')


if __name__ == '__main__':
    main()
