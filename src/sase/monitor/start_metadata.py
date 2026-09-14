"""Metadata reads shared by the monitor-start internals."""

from __future__ import annotations

import json
import os
from typing import Any

from .models import MonitorError


def read_start_meta(artifacts_dir: str) -> dict[str, Any]:
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    with open(meta_path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise MonitorError(f"agent_meta.json at {artifacts_dir!r} is not an object")
    return data


__all__ = [
    "read_start_meta",
]
