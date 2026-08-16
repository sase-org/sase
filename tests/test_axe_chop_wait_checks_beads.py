"""Bead dependency tests for the wait_checks chop script."""

import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import sase.bead.store_locator as bead_store_locator
import sase.scripts.sase_chop_sidecar_auto_sync as sidecar_auto_sync_chop
import sase.scripts.sase_chop_wait_checks as wait_checks_module
from sase._sidecar_auto_sync import SidecarSyncResult
from sase.axe.chop_script_context import ChopScriptContext
from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.chops.builtin import BuiltinChopRuntime
from sase.chops.sdk import ChopLogger
from sase.core.wait_dependency_resolution import (
    WaitDependencyIndex,
    dependency_resolution_status,
)

from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import make_waiting_agent, run_wait_checks


def _seed_wait_bead_store(base: Path) -> tuple[Path, str, str]:
    root = base / "bead-store"
    with BeadProject.init(root) as project:
        open_bead = project.create("Open", IssueType.PLAN)
        closed_bead = project.create("Closed", IssueType.PLAN)
        project.close([closed_bead.id])
    return root, open_bead.id, closed_bead.id


def _point_waits_at_bead_store(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
) -> None:
    monkeypatch.setattr(
        bead_store_locator,
        "canonical_beads_dir_for_project",
        lambda _project: root / "sdd/beads",
    )


def test_dependency_resolution_requires_closed_beads() -> None:
    index = WaitDependencyIndex.empty()

    assert dependency_resolution_status(
        index,
        [],
        wait_beads=["sase-1"],
        closed_bead_ids={"sase-1"},
    ).resolved
    assert not dependency_resolution_status(
        index,
        [],
        wait_beads=["sase-1"],
        closed_bead_ids=set(),
    ).resolved
    assert not dependency_resolution_status(
        index,
        [],
        wait_beads=["sase-1"],
        closed_bead_ids=None,
    ).resolved
    assert not dependency_resolution_status(
        index,
        [],
        wait_beads=[object()],
        closed_bead_ids={"sase-1"},
    ).resolved


def test_dependency_resolution_ands_agent_and_bead_conditions() -> None:
    index = WaitDependencyIndex.empty()

    assert not dependency_resolution_status(
        index,
        ["agent"],
        resolved_deps=["agent"],
        wait_beads=["sase-1"],
        closed_bead_ids=set(),
    ).resolved
    assert not dependency_resolution_status(
        index,
        ["agent"],
        wait_beads=["sase-1"],
        closed_bead_ids={"sase-1"},
    ).resolved


def test_dependency_resolution_does_not_memoize_beads() -> None:
    assert not dependency_resolution_status(
        WaitDependencyIndex.empty(),
        [],
        resolved_deps=["sase-1"],
        wait_beads=["sase-1"],
        closed_bead_ids=set(),
    ).resolved


def test_wait_checks_resolves_closed_bead_only_wait(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, _, closed_bead = _seed_wait_bead_store(tmp_path)
    _point_waits_at_bead_store(monkeypatch, root)
    waiter_dir = make_waiting_agent(
        tmp_path,
        wait_for_beads=[closed_bead],
    )

    run_wait_checks(tmp_path, monkeypatch)

    assert json.loads((waiter_dir / "ready.json").read_text()) == {"resolved_deps": []}
    assert f"waited on: beads: {closed_bead}" in capsys.readouterr().out


@pytest.mark.parametrize("bead_kind", ["open", "missing"])
def test_wait_checks_keeps_unclosed_bead_only_wait_parked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bead_kind: str,
) -> None:
    root, open_bead, _ = _seed_wait_bead_store(tmp_path)
    _point_waits_at_bead_store(monkeypatch, root)
    bead_id = open_bead if bead_kind == "open" else "missing-999"
    waiter_dir = make_waiting_agent(tmp_path, wait_for_beads=[bead_id])

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


def test_wait_checks_keeps_bead_wait_parked_when_store_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        bead_store_locator,
        "canonical_beads_dir_for_project",
        lambda _project: None,
    )
    waiter_dir = make_waiting_agent(tmp_path, wait_for_beads=["sase-1"])

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


def test_wait_checks_mixed_agent_and_bead_wait_requires_both(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, open_bead, _ = _seed_wait_bead_store(tmp_path)
    _point_waits_at_bead_store(monkeypatch, root)
    make_agent(
        tmp_path,
        "proj",
        "20260720101010",
        "dep",
        done=True,
        outcome="completed",
    )
    waiter_dir = make_waiting_agent(
        tmp_path,
        "dep",
        wait_for_beads=[open_bead],
    )

    run_wait_checks(tmp_path, monkeypatch)
    assert not (waiter_dir / "ready.json").exists()

    with BeadProject(root) as project:
        project.close([open_bead])
    run_wait_checks(tmp_path, monkeypatch)

    assert json.loads((waiter_dir / "ready.json").read_text()) == {
        "resolved_deps": ["dep"]
    }


def test_wait_checks_reads_each_project_bead_store_once_per_cycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_waiting_agent(tmp_path, suffix="one", wait_for_beads=["sase-1"])
    make_waiting_agent(tmp_path, suffix="two", wait_for_beads=["sase-1"])
    lookup = MagicMock(return_value=frozenset({"sase-1"}))
    monkeypatch.setattr(wait_checks_module, "closed_bead_ids_for_project", lookup)

    run_wait_checks(tmp_path, monkeypatch)

    lookup.assert_called_once_with("proj")


def test_wait_checks_observes_closed_bead_after_sidecar_auto_sync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A live bead waiter's project is hinted and its beads role synced.

    This covers the waiter-driven refresh path retired in favor of
    ``sidecar_auto_sync`` (sase-mq.8.1): a project with a live agent parked
    on ``%wait(bead=...)`` gets its ``beads`` role converged even though it
    has not opted that role into ``auto_sync``.
    """
    root, open_bead, _ = _seed_wait_bead_store(tmp_path)
    _point_waits_at_bead_store(monkeypatch, root)
    waiter_dir = make_waiting_agent(tmp_path, wait_for_beads=[open_bead])
    run_wait_checks(tmp_path, monkeypatch)
    assert not (waiter_dir / "ready.json").exists()

    monkeypatch.setattr(
        sidecar_auto_sync_chop, "bead_refresh_mode", lambda: "background"
    )
    monkeypatch.setattr(
        sidecar_auto_sync_chop,
        "_projects_with_live_bead_waits",
        lambda _root: frozenset({"proj"}),
    )
    monkeypatch.setattr(sidecar_auto_sync_chop, "sase_projects_dir", lambda: tmp_path)
    monkeypatch.setattr(
        sidecar_auto_sync_chop, "mark_sidecar_sync_hint", lambda *_a: None
    )
    monkeypatch.setattr(
        sidecar_auto_sync_chop,
        "_enabled_project_records",
        lambda: [
            SimpleNamespace(
                is_project=True,
                workspace_dir=str(tmp_path / "proj"),
                project_name="proj",
                project_file=None,
            )
        ],
    )
    monkeypatch.setattr(sidecar_auto_sync_chop, "auto_sync_roles", lambda _primary: ())
    monkeypatch.setattr(
        sidecar_auto_sync_chop, "pending_sidecar_sync_roles", lambda _project_key: ()
    )

    def close_bead_during_sync(
        project: str,
        role: str,
        *,
        project_file: str | None = None,
        require_auto_sync_opt_in: bool = True,
    ) -> SidecarSyncResult:
        assert project == "proj"
        assert role == "beads"
        # A live bead waiter unblocks even without an auto_sync opt-in.
        assert require_auto_sync_opt_in is False
        with BeadProject(root) as bead_project:
            bead_project.close([open_bead])
        return SidecarSyncResult(project, role, "refreshed", "closed")

    monkeypatch.setattr(
        sidecar_auto_sync_chop,
        "sync_primary_sidecar_role",
        close_bead_during_sync,
    )
    runtime = BuiltinChopRuntime(
        name="sidecar_auto_sync",
        context=ChopScriptContext(
            max_hook_runners=1,
            max_agent_runners=1,
            zombie_timeout_seconds=60,
            query="",
            lumberjack_name="waits",
            state_dir=str(tmp_path / "state"),
            all_patches_file=str(tmp_path / "all.json"),
            filtered_patches_file=str(tmp_path / "filtered.json"),
        ),
        log=ChopLogger(stdout=StringIO(), stderr=StringIO()),
    )

    sync_result = sidecar_auto_sync_chop._run(runtime)
    run_wait_checks(tmp_path, monkeypatch)

    assert sync_result.counters["refreshed"] == 1
    assert json.loads((waiter_dir / "ready.json").read_text()) == {"resolved_deps": []}
