"""Legacy-v1 transport fixtures shared by the agents-sync reader tests.

Production no longer exports v1 bundles, so the writer that materializes one
lives with the tests that exercise the surviving v1 reader and import paths.
"""

from __future__ import annotations

from pathlib import Path

from sase.agents_sync.io import atomic_write_bytes, atomic_write_json
from sase.agents_sync.models import BUNDLE_SCHEMA_VERSION, AgentBundle


def write_bundle(repo_root: Path, bundle: AgentBundle) -> None:
    """Write the three files of one legacy-v1 transport bundle."""

    bundle_dir = repo_root / "agents" / bundle.metadata.name
    bundle_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(bundle_dir / "meta.json", bundle.metadata.to_json_dict())
    atomic_write_json(
        bundle_dir / "commits.json",
        {
            "schema_version": BUNDLE_SCHEMA_VERSION,
            "commits": [record.to_json_dict() for record in bundle.commits],
        },
    )
    atomic_write_bytes(bundle_dir / "chat.md", bundle.chat_bytes)
