"""Persistence helpers for agent-family runtime metadata."""

from __future__ import annotations

from collections.abc import Mapping

from sase.axe.run_agent_helpers import update_meta_field


def record_family_runtime_metadata(
    artifacts_dir: str,
    metadata_fields: Mapping[str, object],
) -> None:
    """Persist family runtime fields, including explicit ``None`` clears."""

    for key, value in metadata_fields.items():
        update_meta_field(artifacts_dir, key, value)
