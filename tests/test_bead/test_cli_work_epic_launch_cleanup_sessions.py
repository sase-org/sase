"""Agent-session cleanup tests for epic ``sase bead work``."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.agent.names import (
    AgentNameWipeResult,
    claim_registered_name,
)
from sase.bead import cli as bead_cli
from sase.bead.cli_work_cleanup_apply import revalidate_bead_work_launch_selection
from sase.bead.cli_work_cleanup_selection import select_bead_work_launch
from sase.bead.cli_work_cleanup_types import BeadWorkLaunchSelection, BeadWorkSlot
from sase.bead.cli_work_cleanup_types import CleanupTarget
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


def _write_agent_session_member(
    home: Path,
    agent_session_name: str,
    suffix: str,
    *,
    bead_id: str | None,
    role: str,
    outcome: str = "failed",
) -> Path:
    return write_bead_agent_meta(
        home,
        f"{agent_session_name}{suffix}",
        bead_id=bead_id,
        done=True,
        outcome=outcome,
        agent_session=agent_session_name,
        agent_session_role=role,
    )


def _stub_agent_session_wipe(
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
        lambda query, extra_env=None, segment_extra_env=None, origin=None: (
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


def test_work_beadless_agent_session_members_do_not_wedge_retry(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)
    fake_home = project_dir / "home"
    fake_home.mkdir()
    agent_session_name = phase_ids[0]
    members = {
        f"{agent_session_name}--plan",
        f"{agent_session_name}--code",
        f"{agent_session_name}--1",
        f"{agent_session_name}--mon-0",
    }
    _write_agent_session_member(
        fake_home,
        agent_session_name,
        "--plan",
        bead_id=agent_session_name,
        role="plan",
        outcome="completed",
    )
    _write_agent_session_member(
        fake_home, agent_session_name, "--code", bead_id=agent_session_name, role="code"
    )
    _write_agent_session_member(
        fake_home, agent_session_name, "--1", bead_id=None, role="code"
    )
    _write_agent_session_member(
        fake_home, agent_session_name, "--mon-0", bead_id=None, role="monitor"
    )
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    wiped = _stub_agent_session_wipe(monkeypatch, members)
    launched = _stub_launch(monkeypatch)

    bead_cli.handle_bead_work(make_args(epic_id, yes_to_all=True))

    err = capsys.readouterr().err
    assert "not associated with expected bead" not in err
    assert set(wiped) == members
    assert len(launched) == 1
    assert agent_session_name in launched[0]
    assert "no bead metadata; matched by agent session membership" in err
    for member in members:
        assert member in err


def test_work_conflicting_agent_session_bead_still_blocks(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)
    fake_home = project_dir / "home"
    fake_home.mkdir()
    agent_session_name = phase_ids[0]
    conflict_name = f"{agent_session_name}--1"
    _write_agent_session_member(
        fake_home,
        agent_session_name,
        "--plan",
        bead_id=agent_session_name,
        role="plan",
        outcome="completed",
    )
    _write_agent_session_member(
        fake_home, agent_session_name, "--1", bead_id="unrelated-epic.1", role="code"
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


def test_work_agent_session_member_with_ancestor_epic_bead_is_accepted(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)
    fake_home = project_dir / "home"
    fake_home.mkdir()
    agent_session_name = phase_ids[0]
    plan_name = f"{agent_session_name}--plan"
    member_name = f"{agent_session_name}--1"
    _write_agent_session_member(
        fake_home,
        agent_session_name,
        "--plan",
        bead_id=agent_session_name,
        role="plan",
        outcome="completed",
    )
    artifact_dir = _write_agent_session_member(
        fake_home, agent_session_name, "--1", bead_id=None, role="code"
    )
    meta_path = artifact_dir / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["epic_bead_id"] = epic_id
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    wiped = _stub_agent_session_wipe(monkeypatch, {plan_name, member_name})
    launched = _stub_launch(monkeypatch)

    bead_cli.handle_bead_work(make_args(epic_id, yes_to_all=True))

    assert set(wiped) == {plan_name, member_name}
    assert len(launched) == 1


def test_work_reports_every_agent_session_blocker_in_one_run(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)
    fake_home = project_dir / "home"
    fake_home.mkdir()
    agent_session_name = phase_ids[0]
    first = f"{agent_session_name}--1"
    second = f"{agent_session_name}--2"
    _write_agent_session_member(
        fake_home,
        agent_session_name,
        "--plan",
        bead_id=agent_session_name,
        role="plan",
        outcome="completed",
    )
    _write_agent_session_member(
        fake_home, agent_session_name, "--1", bead_id="unrelated-alpha.1", role="code"
    )
    _write_agent_session_member(
        fake_home, agent_session_name, "--2", bead_id="unrelated-beta.1", role="code"
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
    agent_session_name = phase_ids[0]
    _write_agent_session_member(
        fake_home,
        agent_session_name,
        "--plan",
        bead_id=agent_session_name,
        role="plan",
        outcome="completed",
    )
    _write_agent_session_member(
        fake_home, agent_session_name, "--1", bead_id="unrelated-epic.1", role="code"
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
    assert current_owner_agent_name_key(phase_ids[0], identity) == owner_key
    claim_registered_name(phase_ids[0], artifact_dir, replace_existing=True)
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


def test_task_work_accepts_beadless_agent_session_member(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    task_id = seed_task(project_dir)
    fake_home = project_dir / "home"
    fake_home.mkdir()
    members = {f"{task_id}--code", f"{task_id}--1"}
    _write_agent_session_member(
        fake_home, task_id, "--code", bead_id=task_id, role="code"
    )
    _write_agent_session_member(fake_home, task_id, "--1", bead_id=None, role="code")
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setattr(
        "sase.bead.cli_work_task.resolve_task_vcs_launch_context",
        lambda: VCSLaunchContext(vcs_workflow="git", project_name="sase"),
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_task.checkpoint_task_work_launch",
        lambda *_args, **_kwargs: True,
    )
    wiped = _stub_agent_session_wipe(monkeypatch, members)
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
    agent_session_name = phase_ids[0]
    _write_agent_session_member(
        fake_home, agent_session_name, "--1", bead_id="unrelated-alpha.1", role="code"
    )
    _write_agent_session_member(
        fake_home, agent_session_name, "--2", bead_id="unrelated-beta.1", role="code"
    )
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    selection = select_bead_work_launch(
        slots=(_phase_slot(agent_session_name),),
        bead_assignees={},
    )

    blocked_names = {target.name for target in selection.blocked_targets}
    assert blocked_names == {f"{agent_session_name}--1", f"{agent_session_name}--2"}
    assert selection.launch_names == frozenset()
    assert selection.destructive_targets == ()


def test_select_bead_work_launch_uses_one_registry_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slots = (
        _phase_slot("epic.1"),
        _phase_slot("epic.2"),
        _phase_slot("epic.3"),
    )
    lookup_names: list[str] = []
    snapshot_calls = 0

    class Snapshot:
        def lookup(self, name: str) -> dict[str, object] | None:
            lookup_names.append(name)
            return {"name": name}

    def fake_snapshot() -> Snapshot:
        nonlocal snapshot_calls
        snapshot_calls += 1
        return Snapshot()

    monkeypatch.setattr(
        "sase.bead.cli_work_cleanup_selection.load_agent_owner_view",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "sase.agent.names.registered_name_reservation_snapshot",
        fake_snapshot,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_cleanup_selection.classify_slot_owner",
        lambda slot, owner, **_kwargs: (
            CleanupTarget(
                name=slot.owner_name,
                action="REMOVE",
                current_state="failed",
                detail="done",
                expected_bead_id=slot.expected_bead_id,
                slot_id=slot.slot_id,
            ),
        ),
    )

    selection = select_bead_work_launch(slots=slots, bead_assignees={})

    assert snapshot_calls == 1
    assert lookup_names == ["epic.1", "epic.2", "epic.3"]
    assert selection.launch_names == frozenset({"epic.1", "epic.2", "epic.3"})


def test_revalidate_raises_when_blocker_appears_after_preview(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _epic_id, phase_ids = seed_diamond(project_dir)
    fake_home = project_dir / "home"
    fake_home.mkdir()
    agent_session_name = phase_ids[0]
    _write_agent_session_member(
        fake_home, agent_session_name, "--1", bead_id="unrelated-epic.1", role="code"
    )
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    previous = BeadWorkLaunchSelection(
        slots=(_phase_slot(agent_session_name),),
        targets=(),
        launch_names=frozenset({agent_session_name}),
    )

    with pytest.raises(
        ForcedReuseCleanupError, match="not associated with expected bead"
    ):
        revalidate_bead_work_launch_selection(previous, bead_assignees={})
