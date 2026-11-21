"""Shared setup helpers for the artifact-protection-scan test modules.

Split from ``tests.test_artifact_protection_scan``; the original module
re-exports its tests so its import path keeps working.

Names are public so the ``test_artifact_protection_scan_*`` split modules can
share them without importing ``_``-prefixed names across files.
"""

from __future__ import annotations

from pathlib import Path

from sase._repo_inventory_models import RepoRecord


def make_repo_record(
    name: str,
    path: Path,
    *,
    kind: str = "sidecar",
    exists: bool = True,
) -> RepoRecord:
    """Build a test inventory record for the protection-scan fixtures."""
    return RepoRecord(
        name=name,
        kind=kind,  # type: ignore[arg-type]
        project="sase",
        project_key="gh_sase-org__sase",
        path=str(path),
        exists=exists,
        auto_clone=False,
        description=None,
        source="test",
        env_name=None,
        slug=f"sase--{name}" if kind == "sidecar" else None,
    )
