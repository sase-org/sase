"""Shared formatting helpers for builtin@commit repair support."""

from __future__ import annotations

import re

_ARTIFACT_LABEL_RE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_STREAM_CHARS = 4000


def _artifact_label(label: str) -> str:
    return _ARTIFACT_LABEL_RE.sub("_", label).strip("._") or "stitch"


def _bound_stream(text: str) -> str:
    if len(text) <= _MAX_STREAM_CHARS:
        return text
    omitted = len(text) - _MAX_STREAM_CHARS
    return f"{text[:_MAX_STREAM_CHARS]}... [{omitted} more chars truncated]"


__all__ = [
    "_artifact_label",
    "_bound_stream",
]
