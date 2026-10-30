"""Historical plans-sidecar prompt migration into the canonical archive."""

from sase.agents_sync.prompt_archive.migration.orchestration import (
    migrate_prompt_archive,
)

__all__ = [
    "migrate_prompt_archive",
]
