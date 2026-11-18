"""AXE-owned dispatch metadata for durable typed chop admission."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ._chop_typed_admission_batch import resume_typed_chop_batch
from ._chop_typed_admission_dispatch import (
    launch_descriptor_from_metadata,
    make_axe_chop_agent_dispatcher,
)
from ._chop_typed_admission_utils import (
    AXE_CHOP_SOURCE_SURFACE,
    UNIT_DISPATCH_METADATA_KEY,
    chop_batch_cancelled_for_typed_request,
)


def is_axe_chop_typed_request(data: Mapping[str, Any]) -> bool:
    """Return whether a typed admission bundle is owned by an AXE chop run."""
    return str(data.get("source_surface") or "") == AXE_CHOP_SOURCE_SURFACE


__all__ = [
    "AXE_CHOP_SOURCE_SURFACE",
    "UNIT_DISPATCH_METADATA_KEY",
    "chop_batch_cancelled_for_typed_request",
    "is_axe_chop_typed_request",
    "launch_descriptor_from_metadata",
    "make_axe_chop_agent_dispatcher",
    "resume_typed_chop_batch",
]
