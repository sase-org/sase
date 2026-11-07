"""Unavailable-source labels for projects whose sidecars are not connected.

A project registered on this machine but never launched here has no SDD store
record and no sidecar clones. Retention still fails closed for it, but the
unavailable source names the cause; a connected project whose clone is missing
keeps the bare ``<project>:<role>`` label.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase._repo_inventory_models import RepoInventory, RepoRecord
from sase.core.agent_artifact_run_protection import (
    collect_ace_run_retention_protections,
)
from sase.core.agent_artifact_run_trash_ops import purge_ace_run_trash
from sase.sdd.store import write_sdd_store_record


def _record(name: str, path: Path, *, kind: str = "sidecar") -> RepoRecord:
    return RepoRecord(
        name=name,
        kind=kind,  # type: ignore[arg-type]
        project="proj",
        project_key="proj",
        path=str(path),
        exists=path.is_dir(),
        auto_clone=False,
        description=None,
        source="test",
        env_name=None,
        slug=f"proj--{name}" if kind == "sidecar" else None,
    )


@pytest.mark.parametrize(
    ("connected", "expected"),
    [
        (False, "proj:beads (sidecars not connected on this machine)"),
        (True, "proj:beads"),
    ],
)
def test_missing_beads_sidecar_label_names_unconnected_projects_and_still_blocks(
    tmp_path: Path,
    connected: bool,
    expected: str,
) -> None:
    projects_root = tmp_path / "projects"
    primary = tmp_path / "primary"
    plans = tmp_path / "plans"
    for path in (projects_root, primary, plans):
        path.mkdir()
    if connected:
        write_sdd_store_record(
            primary,
            {
                "storage": "separate_repo",
                "provider": "github",
                "remote_url": "https://example.test/proj--plans.git",
                "discovery": "found",
            },
        )

    snapshot = collect_ace_run_retention_protections(
        projects_root=projects_root,
        artifact_index_path=tmp_path / "missing.sqlite",
        inventory=RepoInventory(
            (
                _record("proj", primary, kind="primary"),
                _record("plans", plans),
                _record("beads", tmp_path / "missing-beads"),
            )
        ),
    )

    assert snapshot.sources_unavailable == (expected,)
    purge = purge_ace_run_trash(
        snapshot,
        projects_root=projects_root,
        trash_root=tmp_path / "trash",
        index_path=tmp_path / "missing.sqlite",
    )
    assert purge.status == "blocked"
    assert purge.blocked_reason == "protection_unavailable"
    assert purge.purged == 0
