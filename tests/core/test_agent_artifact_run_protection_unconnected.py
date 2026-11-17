"""Unavailable-source labels for projects whose sidecars are not connected.

A project registered on this machine but never launched here has no SDD store
record and no sidecar clones. Retention still fails closed for it, but the
unavailable source names the cause; a connected project whose clone is missing
keeps the bare ``<project>:<role>`` label.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase._repo_inventory_models import RepoInventory, RepoRecord
from sase.bead.model import Status
from sase.core import agent_artifact_run_protection as protection
from sase.core.agent_artifact_run_protection import (
    collect_ace_run_retention_protections,
)
from sase.core.agent_artifact_run_retention import (
    AceRunRetentionPolicy,
    plan_ace_run_retention,
)
from sase.core.agent_artifact_run_trash_ops import purge_ace_run_trash
from sase.sdd.store import write_sdd_store_record
from tests.main.repo_init_handler_helpers import _mark_managed_project


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
    _mark_managed_project(primary)
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


def test_managed_unconnected_project_still_blocks_both_roles(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    primary = tmp_path / "primary"
    for path in (projects_root, primary):
        path.mkdir()
    _mark_managed_project(primary)

    snapshot = collect_ace_run_retention_protections(
        projects_root=projects_root,
        artifact_index_path=tmp_path / "missing.sqlite",
        inventory=RepoInventory(
            (
                _record("proj", primary, kind="primary"),
                _record("beads", tmp_path / "missing-beads"),
                _record("plans", tmp_path / "missing-plans"),
            )
        ),
    )

    assert snapshot.sources_unavailable == (
        "proj:beads (sidecars not connected on this machine)",
        "proj:plans (sidecars not connected on this machine)",
    )


def test_unmanaged_unconnected_project_adds_no_unavailable_source(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    primary = tmp_path / "primary"
    for path in (projects_root, primary):
        path.mkdir()
    _mark_managed_project(primary, config="is_sase_managed: false\n")

    snapshot = collect_ace_run_retention_protections(
        projects_root=projects_root,
        artifact_index_path=tmp_path / "missing.sqlite",
        inventory=RepoInventory(
            (
                _record("proj", primary, kind="primary"),
                _record("beads", tmp_path / "missing-beads"),
                _record("plans", tmp_path / "missing-plans"),
            )
        ),
    )

    assert snapshot.sources_unavailable == ()
    purge = purge_ace_run_trash(
        snapshot,
        projects_root=projects_root,
        trash_root=tmp_path / "trash",
        index_path=tmp_path / "missing.sqlite",
    )
    assert purge.status != "blocked"
    assert purge.blocked_reason != "protection_unavailable"


def test_unmanaged_project_with_live_beads_clone_is_scanned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects_root = tmp_path / "projects"
    primary = tmp_path / "primary"
    beads = tmp_path / "beads"
    for path in (projects_root, primary, beads):
        path.mkdir()
    _mark_managed_project(primary, config="is_sase_managed: false\n")
    referenced = str(
        projects_root / "proj" / "artifacts" / "ace-run" / "20260401000000"
    )
    monkeypatch.setattr(
        protection.rust_beads,
        "list_issues",
        lambda _root: [
            SimpleNamespace(
                id="sase-open",
                status=Status.IN_PROGRESS,
                description=f"uses {referenced}",
                design="",
                refs=(),
                notes=(),
                links=(),
            )
        ],
    )

    snapshot = collect_ace_run_retention_protections(
        projects_root=projects_root,
        artifact_index_path=tmp_path / "missing.sqlite",
        inventory=RepoInventory(
            (
                _record("proj", primary, kind="primary"),
                _record("beads", beads),
                _record("plans", tmp_path / "missing-plans"),
            )
        ),
    )

    assert snapshot.sources_unavailable == ()
    assert str(Path(referenced).expanduser().resolve(strict=False)) in (
        snapshot.protected_dirs
    )
    assert snapshot.non_closed_bead_ids_by_project == {"proj": frozenset({"sase-open"})}


def test_plan_with_only_unmanaged_project_is_not_protection_unavailable(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    primary = tmp_path / "primary"
    for path in (projects_root, primary):
        path.mkdir()
    _mark_managed_project(primary, config="is_sase_managed: false\n")

    snapshot = collect_ace_run_retention_protections(
        projects_root=projects_root,
        artifact_index_path=tmp_path / "missing.sqlite",
        inventory=RepoInventory(
            (
                _record("proj", primary, kind="primary"),
                _record("beads", tmp_path / "missing-beads"),
                _record("plans", tmp_path / "missing-plans"),
            )
        ),
    )
    assert snapshot.sources_unavailable == ()

    plan = plan_ace_run_retention(
        AceRunRetentionPolicy(
            now=datetime(2026, 9, 12, 12, 0, 0),
            keep_recent_months=2,
            projects_root=projects_root,
        ),
        protections=snapshot,
    )

    assert plan.sources_unavailable == ()
