"""Agent metadata enrichment facade.

The implementation lives in focused sibling modules so each file stays small
while this stable import path continues to expose the public helpers.
"""

from __future__ import annotations

from ._meta_enrichment_filesystem import enrich_agent_from_meta
from ._meta_enrichment_prompt_markers import (
    enrich_agent_from_prompt_markers,
    enrich_agent_from_prompt_markers_wire,
)
from ._meta_enrichment_wire import enrich_agent_from_meta_wire

__all__ = [
    "enrich_agent_from_meta",
    "enrich_agent_from_meta_wire",
    "enrich_agent_from_prompt_markers",
    "enrich_agent_from_prompt_markers_wire",
]
