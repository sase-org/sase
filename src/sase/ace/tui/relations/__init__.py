"""Built-in host-owned Artifacts relation sources."""

from __future__ import annotations

from .beads import build_beads_relation_index
from .documents import build_documents_relation_index
from .files import build_files_relation_index
from .patches import build_patches_relation_index
from .provider import build_provider_relation_index
from .stitches import build_stitches_relation_index

__all__ = [
    "build_beads_relation_index",
    "build_documents_relation_index",
    "build_files_relation_index",
    "build_patches_relation_index",
    "build_provider_relation_index",
    "build_stitches_relation_index",
]
