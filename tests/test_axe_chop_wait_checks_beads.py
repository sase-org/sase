"""Bead dependency tests for the wait_checks chop script."""

import json
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import sase.bead.store_locator as bead_store_locator
import sase.scripts.sase_chop_bead_store_refresh as store_refresh
import sase.scripts.sase_chop_wait_checks as wait_checks_module
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


def test_wait_checks_observes_closed_bead_after_store_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, open_bead, _ = _seed_wait_bead_store(tmp_path)
    beads_dir = root / "sdd/beads"
    _point_waits_at_bead_store(monkeypatch, root)
    waiter_dir = make_waiting_agent(tmp_path, wait_for_beads=[open_bead])
    run_wait_checks(tmp_path, monkeypatch)
    assert not (waiter_dir / "ready.json").exists()

    monkeypatch.setattr(store_refresh, "bead_refresh_mode", lambda: "background")
    monkeypatch.setattr(
        store_refresh,
        "_projects_with_live_bead_waits",
        lambda _root: {"proj"},
    )
    monkeypatch.setattr(store_refresh, "sase_projects_dir", lambda: tmp_path)
    monkeypatch.setattr(
        store_refresh,
        "canonical_beads_dir_for_project",
        lambda _project: beads_dir,
    )

    def close_bead_during_refresh(
        refreshed_dir: Path,
        *,
        lock_timeout: float | None = None,
    ) -> None:
        assert refreshed_dir == beads_dir
        assert lock_timeout is not None
        with BeadProject(root) as project:
            project.close([open_bead])

    monkeypatch.setattr(
        store_refresh,
        "refresh_bead_store",
        close_bead_during_refresh,
    )
    runtime = BuiltinChopRuntime(
        name="bead_store_refresh",
        context=ChopScriptContext(
            max_hook_runners=1,
            max_agent_runners=1,
            zombie_timeout_seconds=60,
            query="",
            lumberjack_name="waits",
            state_dir=str(tmp_path / "state"),
            all_changespecs_file=str(tmp_path / "all.json"),
            filtered_changespecs_file=str(tmp_path / "filtered.json"),
        ),
        log=ChopLogger(stdout=StringIO(), stderr=StringIO()),
    )

    refresh_result = store_refresh._run(runtime)
    run_wait_checks(tmp_path, monkeypatch)

    assert refresh_result.counters["stores_refreshed"] == 1
    assert json.loads((waiter_dir / "ready.json").read_text()) == {"resolved_deps": []}
