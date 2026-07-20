"""Regression tests for the wait_checks chop script."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

import sase.bead.store_locator as bead_store_locator
import sase.scripts.sase_chop_wait_checks as wait_checks_module
from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.core.wait_dependency_resolution import (
    WaitDependencyIndex,
    build_wait_dependency_index,
    dependency_resolution_status,
)

from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import make_waiting_agent, run_wait_checks
from tests._dismissed_completion_helpers import (
    add_archive_identity,
    rebuild_completion_archive,
    write_dismissed_completion,
)


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


def test_named_agent_killed_newest_does_not_resolve(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "foo")
    make_agent(tmp_path, "proj", "20260506010101", "foo", done=True)
    make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "foo",
        done=True,
        outcome="killed",
    )

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


def test_later_same_name_completed_agent_resolves_after_killed(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "foo")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo",
        done=True,
        outcome="killed",
    )
    make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "foo",
        done=True,
        outcome="completed",
    )

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["foo"]}


def test_repeat_stopped_completed_marker_resolves_downstream_wait(
    tmp_path: Path, monkeypatch
) -> None:
    """A repeat-stopped slot still reports `completed`, so the cascade is generic.

    The next downstream waiter must resolve off the stopped predecessor exactly
    like any other completed producer -- the chop never inspects `repeat_stopped`.
    """
    waiter_dir = make_waiting_agent(tmp_path, "foo.2")
    producer_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo.2",
        done=True,
        outcome="completed",
    )
    # Mark the predecessor as a repeat-stopped slot, as the runner would.
    done = json.loads((producer_dir / "done.json").read_text(encoding="utf-8"))
    done.update({"repeat_stopped": True, "stopped_by": "foo.1"})
    (producer_dir / "done.json").write_text(json.dumps(done), encoding="utf-8")

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["foo.2"]}


def test_failed_workflow_name_dependency_does_not_resolve(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "wf")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "wf.1",
        workflow_name="wf",
        done=True,
        outcome="failed",
    )

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


def test_successful_workflow_name_dependency_resolves(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "wf")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "wf.1",
        workflow_name="wf",
        done=True,
        outcome="completed",
    )
    make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "wf.2",
        workflow_name="wf",
        parent_timestamp="20260506010101",
        done=True,
        outcome="completed",
    )

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["wf"]}


def test_clan_wait_does_not_resolve_while_members_are_queued(
    tmp_path: Path,
    monkeypatch,
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "research")
    generation = "20260720080000"

    for index in range(6):
        member_dir = make_agent(
            tmp_path,
            "proj",
            f"20260720080{index + 1}00",
            f"research.{index + 1}",
            done=True,
            outcome="completed",
        )
        meta_path = member_dir / "agent_meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta.update(
            {
                "agent_clan": "research",
                "agent_clan_generation": generation,
            }
        )
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

    for index, name in enumerate(("7", "8", "land"), start=1):
        member_dir = make_agent(
            tmp_path,
            "proj",
            f"20260720081{index}00",
            f"research.{name}",
        )
        meta_path = member_dir / "agent_meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta.update(
            {
                "agent_clan": "research",
                "agent_clan_generation": generation,
            }
        )
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        (member_dir / "waiting.json").write_text(
            json.dumps({"waiting_for": ["research.predecessor"]}),
            encoding="utf-8",
        )

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


def test_clan_wait_writes_ready_after_successful_member_is_dismissed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "research")
    generation = "20260720110000"
    archived = make_agent(
        tmp_path,
        "proj",
        "20260720110100",
        "research.archived",
        done=True,
        outcome="completed",
    )
    archived_meta = add_archive_identity(archived)
    archived_meta.update(
        {
            "agent_clan": "research",
            "agent_clan_generation": generation,
        }
    )
    (archived / "agent_meta.json").write_text(
        json.dumps(archived_meta),
        encoding="utf-8",
    )
    write_dismissed_completion(tmp_path, archived, "research.archived")
    (archived / "done.json").unlink()

    live = make_agent(
        tmp_path,
        "proj",
        "20260720110200",
        "research.live",
        done=True,
        outcome="completed",
    )
    live_meta = json.loads((live / "agent_meta.json").read_text(encoding="utf-8"))
    live_meta.update(
        {
            "agent_clan": "research",
            "agent_clan_generation": generation,
        }
    )
    (live / "agent_meta.json").write_text(json.dumps(live_meta), encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    rebuild_completion_archive()

    run_wait_checks(tmp_path, monkeypatch)

    assert json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8")) == {
        "resolved_deps": ["research"]
    }


def test_shared_resolver_matches_wait_checks_workflow_fixture(
    tmp_path: Path,
    monkeypatch,
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "wf")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "wf.1",
        workflow_name="wf",
        done=True,
        outcome="completed",
    )
    make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "wf.2",
        workflow_name="wf",
        parent_timestamp="20260506010101",
        done=True,
        outcome="completed",
    )

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )
    assert dependency_resolution_status(index, ["wf"]).resolved

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["wf"]}


def test_completed_named_agent_success_path_writes_ready(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "foo")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo",
        done=True,
        outcome="completed",
    )

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["foo"]}
    out = capsys.readouterr().out
    assert "[wait_checks] Dependencies satisfied for waiter-cl" in out
    assert "wait_checks: projects=1 artifacts=2 waiting=1 ready_written=1" in out


def _identity_dep(artifact_dir: Path, *, name: str = "foo") -> dict[str, str]:
    return {
        "project_name": "proj",
        "timestamp": artifact_dir.name,
        "artifact_dir": str(artifact_dir),
        "name": name,
    }


def test_identity_wait_running_parent_stays_unresolved(
    tmp_path: Path, monkeypatch
) -> None:
    parent_dir = make_agent(tmp_path, "proj", "20260506010101", "foo")
    waiter_dir = make_waiting_agent(
        tmp_path,
        "foo",
        wait_for_artifacts=[_identity_dep(parent_dir)],
    )

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


def test_identity_wait_completed_parent_writes_ready(
    tmp_path: Path, monkeypatch
) -> None:
    parent_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo",
        done=True,
        outcome="completed",
    )
    waiter_dir = make_waiting_agent(
        tmp_path,
        "foo",
        wait_for_artifacts=[_identity_dep(parent_dir)],
    )

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["foo"]}


def test_identity_wait_ignores_newer_same_named_agent(
    tmp_path: Path, monkeypatch
) -> None:
    parent_dir = make_agent(tmp_path, "proj", "20260506010101", "foo")
    make_agent(
        tmp_path,
        "proj",
        "20260506020202",
        "foo",
        done=True,
        outcome="completed",
    )
    waiter_dir = make_waiting_agent(
        tmp_path,
        "foo",
        wait_for_artifacts=[_identity_dep(parent_dir)],
    )

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


@pytest.mark.parametrize("outcome", ["failed", "killed", "stopped"])
def test_identity_wait_failed_parent_keeps_waiting(
    tmp_path: Path, monkeypatch, outcome: str
) -> None:
    parent_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo",
        done=True,
        outcome=outcome,
    )
    waiter_dir = make_waiting_agent(
        tmp_path,
        "foo",
        wait_for_artifacts=[_identity_dep(parent_dir)],
    )

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


def test_identity_wait_repeat_stopped_parent_keeps_waiting(
    tmp_path: Path, monkeypatch
) -> None:
    parent_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo",
        done=True,
        outcome="completed",
    )
    done = json.loads((parent_dir / "done.json").read_text(encoding="utf-8"))
    done["repeat_stopped"] = True
    done["stopped_by"] = "foo.1"
    (parent_dir / "done.json").write_text(json.dumps(done), encoding="utf-8")
    waiter_dir = make_waiting_agent(
        tmp_path,
        "foo",
        wait_for_artifacts=[_identity_dep(parent_dir)],
    )

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


def test_identity_wait_resolves_after_failed_parent_is_relaunched(
    tmp_path: Path, monkeypatch
) -> None:
    parent_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo",
        done=True,
        outcome="killed",
    )
    waiter_dir = make_waiting_agent(
        tmp_path,
        "foo",
        wait_for_artifacts=[_identity_dep(parent_dir)],
    )
    make_agent(
        tmp_path,
        "proj",
        "20260506020202",
        "foo",
        done=True,
        outcome="completed",
    )

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["foo"]}


def test_dependency_launched_after_waiter_eventually_resolves(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "late-dep")

    run_wait_checks(tmp_path, monkeypatch)
    assert not (waiter_dir / "ready.json").exists()

    make_agent(
        tmp_path,
        "proj",
        "20260506020202",
        "late-dep",
        done=True,
        outcome="completed",
    )
    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["late-dep"]}


def test_tribe_dependency_resolves_to_next_tribe_entity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    waiter_dir = make_waiting_agent(
        tmp_path,
        "@epic",
        suffix="20260718020000",
    )
    older = make_agent(
        tmp_path,
        "proj",
        "20260718010000",
        "old-epic",
        done=True,
        outcome="completed",
    )
    newer = make_agent(
        tmp_path,
        "proj",
        "20260718030000",
        "new-epic",
        done=True,
        outcome="completed",
    )
    for artifact in (older, newer):
        meta_path = artifact / "agent_meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["tribe"] = "epic"
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["@epic"]}


def test_concrete_indexed_wait_marker_resolves_without_template_marker(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "build-3")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "build-3",
        done=True,
        outcome="completed",
    )

    waiting = json.loads((waiter_dir / "waiting.json").read_text(encoding="utf-8"))
    assert waiting["waiting_for"] == ["build-3"]
    assert all("-@" not in dep for dep in waiting["waiting_for"])

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["build-3"]}


def test_multiple_waiting_dependencies_scan_artifacts_once(
    tmp_path: Path, monkeypatch
) -> None:
    first_waiter = make_waiting_agent(tmp_path, "foo", "wf", suffix="waiter-1")
    second_waiter = make_waiting_agent(tmp_path, "foo", suffix="waiter-2")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo",
        done=True,
        outcome="completed",
    )
    make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "wf",
        workflow_name="wf",
        done=True,
        outcome="completed",
    )
    make_agent(
        tmp_path,
        "proj",
        "20260506010303",
        "wf.child",
        workflow_name="wf",
        parent_timestamp="20260506010202",
        done=True,
        outcome="completed",
    )

    original_read_json_dict = wait_checks_module._read_json_dict
    agent_meta_reads = 0

    def counting_read_json_dict(path: Path) -> dict[str, Any] | None:
        nonlocal agent_meta_reads
        if path.name == "agent_meta.json":
            agent_meta_reads += 1
        return original_read_json_dict(path)

    monkeypatch.setattr(
        wait_checks_module,
        "_read_json_dict",
        counting_read_json_dict,
    )

    run_wait_checks(tmp_path, monkeypatch)

    assert (first_waiter / "ready.json").exists()
    assert (second_waiter / "ready.json").exists()
    assert agent_meta_reads == 5


def test_wait_checks_no_projects_dir_emits_noop_summary(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    run_wait_checks(tmp_path, monkeypatch)

    assert capsys.readouterr().out == (
        "wait_checks: projects=0 artifacts=0 waiting=0 ready_written=0 "
        "reason=no_projects_dir\n"
    )


def test_wait_checks_unresolved_dependency_emits_noop_reason(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    make_waiting_agent(tmp_path, "missing-agent")

    run_wait_checks(tmp_path, monkeypatch)

    out = capsys.readouterr().out
    assert "wait_checks: projects=1 artifacts=1 waiting=1 ready_written=0" in out
    assert "unresolved=1 reason=dependencies_not_ready" in out
