"""Shared probes for the idle-time full-GC policy split."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def safe_probe(fn: Callable[[], Any], default: Any) -> Any:
    """Call a UI probe, returning ``default`` if it raises."""
    try:
        return fn()
    except Exception:
        return default
