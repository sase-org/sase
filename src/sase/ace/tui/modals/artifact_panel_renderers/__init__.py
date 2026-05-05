"""Kind-specific Rich renderers for the artifact panel modal."""

from __future__ import annotations

from ._common import FILE_PREVIEW_LINE_LIMIT, FILE_PREVIEW_MAX_BYTES
from ._detail import render_artifact_detail

__all__ = [
    "FILE_PREVIEW_LINE_LIMIT",
    "FILE_PREVIEW_MAX_BYTES",
    "render_artifact_detail",
]
