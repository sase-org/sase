"""Composed ACE copy-mode target registry."""

from __future__ import annotations

from ._copy_target_artifacts import ARTIFACT_COPY_TARGETS
from ._copy_target_standard import (
    AGENT_COPY_TARGETS,
    AXE_COPY_TARGETS,
    PATCH_COPY_TARGETS,
)
from ._copy_target_types import CopyTarget


COPY_TARGETS: tuple[CopyTarget, ...] = (
    *PATCH_COPY_TARGETS,
    *ARTIFACT_COPY_TARGETS,
    *AGENT_COPY_TARGETS,
    *AXE_COPY_TARGETS,
)


__all__ = [
    "COPY_TARGETS",
]
