"""Shared helpers for the bead_claim_checks chop script tests."""

from __future__ import annotations

from contextlib import contextmanager
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import sase.scripts.sase_chop_bead_claim_checks as claim_checks
from sase.axe.chop_script_context import ChopScriptContext
from sase.bead.model import Issue, Status
from sase.chops.builtin import BuiltinChopRuntime
from sase.chops.sdk import ChopLogger
from tests.test_bead.claims_test_helpers import writable_store_for_beads

_NO_FAIL_PROJECTS: frozenset[str] = frozenset()


def make_runtime(tmp_path: Path) -> BuiltinChopRuntime:
    return BuiltinChopRuntime(
        name="bead_claim_checks",
        context=ChopScriptContext(
            max_hook_runners=1,
            max_agent_runners=1,
            zombie_timeout_seconds=60,
            query="",
            lumberjack_name="waits",
            state_dir=str(tmp_path),
            all_patches_file=str(tmp_path / "all.json"),
            filtered_patches_file=str(tmp_path / "filtered.json"),
        ),
        log=ChopLogger(stdout=StringIO(), stderr=StringIO()),
    )


def make_artifact(
    tmp_path: Path,
    *,
    name: str = "sase-1.1",
    bead_id: str = "sase-1.1",
    project_name: str = "sase",
    promoted: bool | None = False,
    has_marker: bool = True,
    timestamp: str = "20260724120000",
    tombstoned: bool = False,
) -> claim_checks._ClaimArtifact:
    return claim_checks._ClaimArtifact(
        project_name=project_name,
        agent_name=name,
        artifact_dir=tmp_path / timestamp,
        timestamp=timestamp,
        pid=123,
        stopped_at=None,
        bead_id=bead_id,
        bead_claim_promoted=promoted,
        has_bead_claim_marker=has_marker,
        has_reconcile_tombstone=tombstoned,
    )


def tombstone_path(tmp_path: Path, timestamp: str = "20260724120000") -> Path:
    return tmp_path / timestamp / claim_checks.BEAD_CLAIM_RECONCILED_MARKER


def make_claimed_issue(
    *,
    bead_id: str = "sase-1.1",
    assignee: str = "sase-1.1",
) -> Issue:
    return Issue(
        id=bead_id,
        title="Claimed phase",
        status=Status.CLAIMED,
        parent_id="sase-1",
        assignee=assignee,
    )


def _reconciliation(
    *,
    released: tuple[tuple[str, str], ...] = (),
    release_errors: tuple[tuple[str, str], ...] = (),
    held: tuple[tuple[str, str], ...] = (),
) -> claim_checks._ProjectClaimReconciliation:
    return claim_checks._ProjectClaimReconciliation(
        released=frozenset(released),
        release_errors=frozenset(release_errors),
        held=frozenset(held),
    )


def make_tick(
    *,
    snapshot_ok: bool = False,
    scanned: bool = False,
    claimed_count: int = 0,
    released: tuple[tuple[str, str], ...] = (),
    release_errors: tuple[tuple[str, str], ...] = (),
    held: tuple[tuple[str, str], ...] = (),
) -> claim_checks._ProjectClaimTick:
    return claim_checks._ProjectClaimTick(
        snapshot_ok=snapshot_ok,
        scanned=scanned,
        claimed_count=claimed_count,
        reconciliation=_reconciliation(
            released=released,
            release_errors=release_errors,
            held=held,
        ),
    )


def _install_counting_store(
    monkeypatch: pytest.MonkeyPatch,
    beads_dir: Path,
    *,
    fail_projects: frozenset[str] = _NO_FAIL_PROJECTS,
) -> list[str]:
    holders: list[str] = []

    @contextmanager
    def fake_store(project: str, **kwargs: object):
        holders.append(str(kwargs.get("holder", project)))
        if project in fail_projects:
            raise RuntimeError(f"{project} store down")
        yield writable_store_for_beads(beads_dir, project=project)

    monkeypatch.setattr(
        "sase.bead.background_store.writable_bead_store_for_machine",
        fake_store,
    )
    monkeypatch.setattr(
        "sase.bead.background_store.schedule_beads_sidecar_convergence",
        lambda _project: None,
    )
    return holders


def install_leased_apply(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    project: MagicMock | None = None,
    fail_projects: frozenset[str] = _NO_FAIL_PROJECTS,
) -> tuple[list[str], list[Path], MagicMock, MagicMock]:
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    holders = _install_counting_store(
        monkeypatch, beads_dir, fail_projects=fail_projects
    )
    lock_entries: list[Path] = []

    @contextmanager
    def lock(path: Path):
        lock_entries.append(path)
        yield True

    if project is None:
        project = MagicMock()
        project.release_agent_claim.return_value = (make_claimed_issue(), True)
        project.claim_for_agent_wait.return_value = (make_claimed_issue(), True)

    project_context = MagicMock()
    project_context.__enter__.return_value = project
    commit = MagicMock(return_value=True)
    publish = MagicMock()
    monkeypatch.setattr(claim_checks, "refresh_bead_store", lambda _path: None)
    monkeypatch.setattr(
        claim_checks,
        "open_bead_project_for_beads_dir",
        lambda _path: project_context,
    )
    monkeypatch.setattr(claim_checks, "bead_store_write_lock", lock)
    monkeypatch.setattr(claim_checks, "commit_bead_claim_reconciliation", commit)
    monkeypatch.setattr(claim_checks, "publish_bead_claim", publish)
    return holders, lock_entries, commit, publish
