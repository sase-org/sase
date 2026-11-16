"""Shared public helpers for the private Agent Hijack canary modules."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT = "hijack-canary"
WORKSPACE_NUM = 3
SESSION = "canary"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
