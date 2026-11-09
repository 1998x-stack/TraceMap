"""Load TraceMap configuration from a ``.env`` file (stdlib only).

The repository keeps every runtime setting in a single ``.env`` file at the repo
root (see ``.env.example``). This module parses it into ``os.environ``:

* **It never overrides a variable that is already set**, so explicit environment
  variables (CI, tests, ``TRACEMAP_* cmd``) always win.
* **It can be disabled** with ``TRACEMAP_DOTENV=0`` (used by the test suite, the
  Playwright harness and the isolated smoke workflow so they stay hermetic and
  never call a real model).
* No third-party dependency: a small, predictable parser for ``KEY=VALUE`` lines
  with optional surrounding quotes and ``#`` comments.

This must be imported before anything reads ``TRACEMAP_*`` variables.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def repo_root() -> Path:
    """The repository root (…/apps/api/tracemap/config.py → root)."""
    return Path(__file__).resolve().parents[3]


def default_env_file() -> Path:
    override = os.getenv("TRACEMAP_ENV_FILE")
    if override:
        return Path(override).expanduser()
    return repo_root() / ".env"


def parse_env(text: str) -> dict[str, str]:
    """Parse ``.env`` content into a dict. Blank lines and ``#`` comments are
    ignored; an optional leading ``export`` and matching single/double quotes are
    stripped. No shell expansion is performed."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not _KEY_RE.match(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def load_env_file(path: Path, *, override: bool = False) -> list[str]:
    """Load a specific ``.env`` file into ``os.environ``; returns keys applied.

    This always loads the given file (no ``TRACEMAP_DOTENV`` check) so callers
    and tests can load an explicit file deterministically. Use
    :func:`load_default_env` for the automatic, disable-able repository load.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    applied: list[str] = []
    for key, value in parse_env(text).items():
        if override or key not in os.environ:
            os.environ[key] = value
            applied.append(key)
    return applied


def load_default_env() -> list[str]:
    """Auto-load the repository ``.env`` unless ``TRACEMAP_DOTENV=0``."""
    if os.getenv("TRACEMAP_DOTENV", "1").strip() == "0":
        return []
    return load_env_file(default_env_file())


# Load once at import time, before the application reads any TRACEMAP_* value.
load_default_env()
