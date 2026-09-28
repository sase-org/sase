"""Metadata field rendering for the agent detail header.

Facade preserving the original public import path. Content lives in the
split ``_agent_display_header_metadata_*`` modules; only public names are
re-exported here.
"""

from __future__ import annotations

from ._agent_display_header_metadata_fields import append_agent_metadata_fields
from ._agent_display_header_metadata_sections import (
    append_legacy_parallel_members_section,
)

__all__ = [
    "append_agent_metadata_fields",
    "append_legacy_parallel_members_section",
]
