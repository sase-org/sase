"""Forced name-reuse cleanup failure tests for epic ``sase bead work``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.agent.names import AgentNameWipeResult, lookup_registered_name
from sase.bead import cli as bead_cli
from sase.bead.cli_work_cleanup_apply import revalidate_bead_work_launch_selection
from sase.bead.cli_work_cleanup_selection import select_bead_work_launch
from sase.bead.cli_work_cleanup_types import BeadWorkLaunchSelection, BeadWorkSlot
from sase.bead.cli_work_name_cleanup import ForcedReuseCleanupError
from sase.bead.model import Status
from sase.bead.project import BeadProject
from sase.bead.work import VCSLaunchContext

from .cli_work_helpers import (
    FakeLaunchResult,
    make_args,
    seed_diamond,
    seed_task,
    write_bead_agent_meta,
)

pytestmark = pytest.mark.usefixtures("fake_cli_work_xprompts")


@pytest.mark.parametrize(
    ("conflict_target", "container_kind"),
    [
        pytest.param("phase", "clan", id="phase-clan-container"),
        pytest.param("land", "clan", id="land-clan-container"),
    ],
)
def test_work_expected_name_container_conflict_aborts_before_mutation(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    conflict_target: str,
    container_kind: str,
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)
    conflict_name = phase_ids[0] if conflict_target == "phase" else f"{epic_id}.land"
    fake_home = project_dir / "home"
    fake_home.mkdir()
    write_bead_agent_meta(
        fake_home,
        f"{conflict_name}.member",
        bead_id=phase_ids[0] if conflict_target == "phase" else epic_id,
        agent_clan=conflict_name,
    )
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    launched: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: (
            launched.append(query) or FakeLaunchResult()
        ),
    )
    monkeypatch.setattr(
        "sase.bead.sync.commit_epic_graph_checkpoint",
        lambda *args, **kwargs: pytest.fail("aborted launch must not commit"),
    )

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(epic_id, yes_to_all=True))
    assert excinfo.value.code == 1

    err = capsys.readouterr().err
    assert (
        f"agent name '{conflict_name}' is reserved by a populated {container_kind} "
        "container" in err
    )
    assert "cannot be force-reused" in err
    assert launched == []
    with BeadProject(project_dir) as proj:
        assert proj.show(epic_id).is_ready_to_work is False
        for phase_id in phase_ids:
            phase = proj.show(phase_id)
            assert phase.status == Status.OPEN
            assert phase.assignee == ""


@pytest.mark.parametrize(
    "failure_mode",
    [
        pytest.param("member-errors", id="member-wipe-errors"),
        pytest.param("residual-family", id="residual-family-reservation"),
    ],
)
def test_work_family_cleanup_failure_aborts_before_mutation(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
) -> None:
    from sase.agent.names import AgentNameWipeResult

    epic_id, phase_ids = seed_diamond(project_dir)
    fake_home = project_dir / "home"
    fake_home.mkdir()
    family_name = phase_ids[0]
    plan_name = f"{family_name}--plan"
    code_name = f"{family_name}--code"
    write_bead_agent_meta(
        fake_home,
        plan_name,
        bead_id=phase_ids[0],
        done=True,
        outcome="completed",
        agent_family=family_name,
        agent_family_role="plan",
    )
    write_bead_agent_meta(
        fake_home,
        code_name,
        bead_id=phase_ids[0],
        done=True,
        outcome="failed",
        agent_family=family_name,
        agent_family_role="code",
    )
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    def fake_wipe(name: str) -> AgentNameWipeResult:
        if name == plan_name and failure_mode == "member-errors":
            return AgentNameWipeResult(
                target_name=name,
                found=True,
                errors=("kaboom",),
            )
        if name in {plan_name, code_name}:
            if failure_mode == "residual-family":
                return AgentNameWipeResult(
                    target_name=name,
                    found=True,
                    registry_names_removed=(),
                )
            return AgentNameWipeResult(
                target_name=name,
                found=True,
                registry_names_removed=(name,),
            )
        return AgentNameWipeResult(target_name=name, found=False)

    monkeypatch.setattr("sase.agent.names.wipe_agent_name_for_reuse", fake_wipe)
    monkeypatch.setattr(
        "sase.agent.names.rebuild_name_registry",
        lambda: {
            "entries": {family_name: {}} if failure_mode == "residual-family" else {}
        },
    )
    launched: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: (
            launched.append(query) or FakeLaunchResult()
        ),
    )
    monkeypatch.setattr(
        "sase.bead.sync.commit_epic_graph_checkpoint",
        lambda *args, **kwargs: pytest.fail("aborted launch must not commit"),
    )

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(epic_id, yes_to_all=True))
    assert excinfo.value.code == 1
    assert launched == []
    with BeadProject(project_dir) as proj:
        assert proj.show(epic_id).is_ready_to_work is False
        for phase_id in phase_ids:
            phase = proj.show(phase_id)
            assert phase.status == Status.OPEN
            assert phase.assignee == ""


@pytest.mark.parametrize(
    "failure_mode",
    [
        pytest.param("raise", id="wipe-raises"),
        pytest.param("errors", id="wipe-reports-errors"),
        pytest.param("residual", id="name-still-reserved"),
    ],
)
def test_work_force_reuse_cleanup_failure_aborts_before_mutation(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure_mode: str,
) -> None:
    """A failed forced-reuse wipe aborts before any bead mutation or launch."""
    from sase.agent.names import AgentNameWipeResult

    epic_id, phase_ids = seed_diamond(project_dir)
    fake_home = project_dir / "home"
    fake_home.mkdir()
    write_bead_agent_meta(
        fake_home,
        phase_ids[0],
        bead_id=phase_ids[0],
        waiting=True,
    )
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    def fake_wipe(name: str) -> AgentNameWipeResult:
        if failure_mode == "raise":
            raise RuntimeError("kaboom")
        if failure_mode == "errors":
            return AgentNameWipeResult(target_name=name, found=True, errors=("kaboom",))
        # residual: found but never removed from the registry.
        return AgentNameWipeResult(
            target_name=name, found=True, registry_names_removed=()
        )

    monkeypatch.setattr("sase.agent.names.wipe_agent_name_for_reuse", fake_wipe)

    launched: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: (
            launched.append(query) or FakeLaunchResult()
        ),
    )
    monkeypatch.setattr(
        "sase.bead.sync.commit_epic_graph_checkpoint",
        lambda *args, **kwargs: pytest.fail("aborted launch must not commit"),
    )

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(epic_id, yes_to_all=True))
    assert excinfo.value.code == 1

    err = capsys.readouterr().err
    assert "forced reuse cleanup" in err
    assert launched == []
    with BeadProject(project_dir) as proj:
        assert proj.show(epic_id).is_ready_to_work is False
        for pid in phase_ids:
            phase = proj.show(pid)
            assert phase.status == Status.OPEN
            assert phase.assignee == ""


def _write_family_member(
    home: Path,
    family_name: str,
    suffix: str,
    *,
    bead_id: str | None,
    role: str,
    outcome: str = "failed",
) -> Path:
    return write_bead_agent_meta(
        home,
        f"{family_name}{suffix}",
        bead_id=bead_id,
        done=True,
        outcome=outcome,
        agent_family=family_name,
        agent_family_role=role,
    )


def _stub_family_wipe(
    monkeypatch: pytest.MonkeyPatch,
    member_names: set[str],
) -> list[str]:
    wiped: list[str] = []

    def fake_wipe(name: str) -> AgentNameWipeResult:
        wiped.append(name)
        if name in member_names:
            return AgentNameWipeResult(
                target_name=name,
                found=True,
                registry_names_removed=(name,),
            )
        return AgentNameWipeResult(target_name=name, found=False)

    monkeypatch.setattr("sase.agent.names.wipe_agent_name_for_reuse", fake_wipe)
    monkeypatch.setattr(
        "sase.agent.names.rebuild_name_registry", lambda: {"entries": {}}
    )
    return wiped


def _stub_launch(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    launched: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: (
            launched.append(query) or FakeLaunchResult()
        ),
    )
    return launched


def _phase_slot(phase_id: str) -> BeadWorkSlot:
    return BeadWorkSlot(
        slot_id=phase_id,
        owner_name=phase_id,
        expected_bead_id=phase_id,
        launch_name=phase_id,
    )


def test_work_beadless_family_members_do_not_wedge_retry(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)
    fake_home = project_dir / "home"
    fake_home.mkdir()
    family_name = phase_ids[0]
    members = {
        f"{family_name}--plan",
        f"{family_name}--code",
        f"{family_name}--1",
        f"{family_name}--mon-0",
    }
    _write_family_member(
        fake_home,
        family_name,
        "--plan",
        bead_id=family_name,
        role="plan",
        outcome="completed",
    )
    _write_family_member(
        fake_home, family_name, "--code", bead_id=family_name, role="code"
    )
    _write_family_member(fake_home, family_name, "--1", bead_id=None, role="code")
    _write_family_member(
        fake_home, family_name, "--mon-0", bead_id=None, role="monitor"
    )
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    wiped = _stub_family_wipe(monkeypatch, members)
    launched = _stub_launch(monkeypatch)

    bead_cli.handle_bead_work(make_args(epic_id, yes_to_all=True))

    err = capsys.readouterr().err
    assert "not associated with expected bead" not in err
    assert set(wiped) == members
    assert len(launched) == 1
    assert family_name in launched[0]
    assert "no bead metadata; matched by family membership" in err
    for member in members:
        assert member in err


def test_work_conflicting_family_bead_still_blocks(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)
    fake_home = project_dir / "home"
    fake_home.mkdir()
    family_name = phase_ids[0]
    conflict_name = f"{family_name}--1"
    _write_family_member(
        fake_home,
        family_name,
        "--plan",
        bead_id=family_name,
        role="plan",
        outcome="completed",
    )
    _write_family_member(
        fake_home, family_name, "--1", bead_id="unrelated-epic.1", role="code"
    )
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setattr(
        "sase.agent.names.wipe_agent_name_for_reuse",
        lambda name: pytest.fail(f"conflicting member must not be wiped: {name}"),
    )
    launched = _stub_launch(monkeypatch)

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(epic_id, yes_to_all=True))
    assert excinfo.value.code == 1

    err = capsys.readouterr().err
    assert "BLOCKED" in err
    assert conflict_name in err
    assert "unrelated-epic.1" in err
    assert "not associated with expected bead" in err
    assert launched == []
    with BeadProject(project_dir) as proj:
        assert proj.show(epic_id).is_ready_to_work is False
        for phase_id in phase_ids:
            phase = proj.show(phase_id)
            assert phase.status == Status.OPEN
            assert phase.assignee == ""


def test_work_family_member_with_ancestor_epic_bead_is_accepted(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)
    fake_home = project_dir / "home"
    fake_home.mkdir()
    family_name = phase_ids[0]
    plan_name = f"{family_name}--plan"
    member_name = f"{family_name}--1"
    _write_family_member(
        fake_home,
        family_name,
        "--plan",
        bead_id=family_name,
        role="plan",
        outcome="completed",
    )
    artifact_dir = _write_family_member(
        fake_home, family_name, "--1", bead_id=None, role="code"
    )
    meta_path = artifact_dir / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["epic_bead_id"] = epic_id
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    wiped = _stub_family_wipe(monkeypatch, {plan_name, member_name})
    launched = _stub_launch(monkeypatch)

    bead_cli.handle_bead_work(make_args(epic_id, yes_to_all=True))

    assert set(wiped) == {plan_name, member_name}
    assert len(launched) == 1


def test_work_reports_every_family_blocker_in_one_run(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)
    fake_home = project_dir / "home"
    fake_home.mkdir()
    family_name = phase_ids[0]
    first = f"{family_name}--1"
    second = f"{family_name}--2"
    _write_family_member(
        fake_home,
        family_name,
        "--plan",
        bead_id=family_name,
        role="plan",
        outcome="completed",
    )
    _write_family_member(
        fake_home, family_name, "--1", bead_id="unrelated-alpha.1", role="code"
    )
    _write_family_member(
        fake_home, family_name, "--2", bead_id="unrelated-beta.1", role="code"
    )
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    launched = _stub_launch(monkeypatch)

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(epic_id, yes_to_all=True))
    assert excinfo.value.code == 1

    err = capsys.readouterr().err
    assert first in err
    assert second in err
    assert "unrelated-alpha.1" in err
    assert "unrelated-beta.1" in err
    assert launched == []


def test_work_dry_run_renders_blockers_without_mutating(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)
    fake_home = project_dir / "home"
    fake_home.mkdir()
    family_name = phase_ids[0]
    _write_family_member(
        fake_home,
        family_name,
        "--plan",
        bead_id=family_name,
        role="plan",
        outcome="completed",
    )
    _write_family_member(
        fake_home, family_name, "--1", bead_id="unrelated-epic.1", role="code"
    )
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setattr(
        "sase.agent.names.wipe_agent_name_for_reuse",
        lambda name: pytest.fail(f"dry-run must not wipe: {name}"),
    )
    launched = _stub_launch(monkeypatch)

    bead_cli.handle_bead_work(make_args(epic_id, dry_run=True, yes_to_all=True))

    captured = capsys.readouterr()
    assert "BLOCKED" in captured.err
    assert "would abort a real launch" in captured.err
    assert "Multi-prompt (dry run)" in captured.out
    assert launched == []
    with BeadProject(project_dir) as proj:
        assert proj.show(epic_id).is_ready_to_work is False


def test_work_direct_registry_name_mismatch_without_beads_blocks(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        current_owner_agent_name_key,
    )

    epic_id, phase_ids = seed_diamond(project_dir)
    fake_home = project_dir / "home"
    fake_home.mkdir()
    artifact_dir = write_bead_agent_meta(
        fake_home,
        "unrelated-agent",
        bead_id=None,
        done=True,
    )
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    identity = AgentIdentitySnapshot.current()
    owner_key = current_owner_agent_name_key(phase_ids[0], identity)
    real_lookup = lookup_registered_name

    def fake_lookup(name: str) -> dict[str, object] | None:
        if current_owner_agent_name_key(name, identity) == owner_key:
            return {"artifacts_dir": str(artifact_dir), "state": "done"}
        return real_lookup(name)

    monkeypatch.setattr("sase.agent.names.lookup_registered_name", fake_lookup)
    monkeypatch.setattr(
        "sase.agent.names.wipe_agent_name_for_reuse",
        lambda name: pytest.fail(
            f"mismatched registry owner must not be wiped: {name}"
        ),
    )
    launched = _stub_launch(monkeypatch)

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(epic_id, yes_to_all=True))
    assert excinfo.value.code == 1

    err = capsys.readouterr().err
    assert "not associated with expected bead" in err
    assert "unrelated-agent" in err
    assert launched == []
    with BeadProject(project_dir) as proj:
        assert proj.show(epic_id).is_ready_to_work is False


def test_task_work_accepts_beadless_family_member(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    task_id = seed_task(project_dir)
    fake_home = project_dir / "home"
    fake_home.mkdir()
    members = {f"{task_id}--code", f"{task_id}--1"}
    _write_family_member(fake_home, task_id, "--code", bead_id=task_id, role="code")
    _write_family_member(fake_home, task_id, "--1", bead_id=None, role="code")
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setattr(
        "sase.bead.cli_work_task.resolve_task_vcs_launch_context",
        lambda: VCSLaunchContext(vcs_workflow="git", project_name="sase"),
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_task.checkpoint_task_work_launch",
        lambda *_args, **_kwargs: True,
    )
    wiped = _stub_family_wipe(monkeypatch, members)
    launched: list[str] = []
    monkeypatch.setattr(
        "sase.bead.cli_work_task.launch_bead_work_agents",
        lambda query, **_kwargs: launched.append(query) or [FakeLaunchResult()],
    )

    bead_cli.handle_bead_work(make_args(task_id, yes_to_all=True))

    err = capsys.readouterr().err
    assert "not associated with expected bead" not in err
    assert set(wiped) == members
    assert len(launched) == 1
    with BeadProject(project_dir) as project:
        task = project.show(task_id)
        assert (task.status, task.assignee) == (Status.IN_PROGRESS, task_id)


def test_select_bead_work_launch_returns_blocked_targets_instead_of_raising(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _epic_id, phase_ids = seed_diamond(project_dir)
    fake_home = project_dir / "home"
    fake_home.mkdir()
    family_name = phase_ids[0]
    _write_family_member(
        fake_home, family_name, "--1", bead_id="unrelated-alpha.1", role="code"
    )
    _write_family_member(
        fake_home, family_name, "--2", bead_id="unrelated-beta.1", role="code"
    )
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    selection = select_bead_work_launch(
        slots=(_phase_slot(family_name),),
        bead_assignees={},
    )

    blocked_names = {target.name for target in selection.blocked_targets}
    assert blocked_names == {f"{family_name}--1", f"{family_name}--2"}
    assert selection.launch_names == frozenset()
    assert selection.destructive_targets == ()


def test_revalidate_raises_when_blocker_appears_after_preview(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _epic_id, phase_ids = seed_diamond(project_dir)
    fake_home = project_dir / "home"
    fake_home.mkdir()
    family_name = phase_ids[0]
    _write_family_member(
        fake_home, family_name, "--1", bead_id="unrelated-epic.1", role="code"
    )
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    previous = BeadWorkLaunchSelection(
        slots=(_phase_slot(family_name),),
        targets=(),
        launch_names=frozenset({family_name}),
    )

    with pytest.raises(
        ForcedReuseCleanupError, match="not associated with expected bead"
    ):
        revalidate_bead_work_launch_selection(previous, bead_assignees={})
