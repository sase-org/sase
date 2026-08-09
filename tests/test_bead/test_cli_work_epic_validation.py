"""Validation and locking tests for epic ``sase bead work``."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import BeadTier, IssueType, Status
from sase.bead.project import BeadProject

from .cli_work_helpers import make_args, seed_patch_epic, seed_diamond

pytestmark = pytest.mark.usefixtures("fake_cli_work_xprompts")


def test_work_patch_epic_errors_without_project_context(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_patch_epic(project_dir)
    monkeypatch.setattr(
        "sase.bead.project_name.infer_project_name_from_cwd",
        lambda: None,
    )

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(epic_id, dry_run=True, yes=True))

    assert excinfo.value.code == 1
    assert "unable to infer the current SASE project" in capsys.readouterr().err
    with BeadProject(project_dir) as proj:
        assert proj.show(epic_id).is_ready_to_work is False
        for pid in phase_ids:
            assert proj.show(pid).status == Status.OPEN


def test_work_rejects_non_plan_bead(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, phase_ids = seed_diamond(project_dir)

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(phase_ids[0], yes=True))
    assert excinfo.value.code == 1
    assert "only applies to epic plan or task beads" in capsys.readouterr().err


def test_work_missing_bead_json_error_is_one_envelope(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args("sase-missing", json_output=True))

    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "ok": False,
        "mode": "bead_id",
        "epic_id": "sase-missing",
        "error": "issue not found: sase-missing",
    }


def test_work_non_plan_bead_json_error_is_one_envelope(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, phase_ids = seed_diamond(project_dir)

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(phase_ids[0], json_output=True))

    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["mode"] == "bead_id"
    assert payload["epic_id"] == phase_ids[0]
    assert payload["error"].startswith(
        "sase bead work only applies to epic plan or task beads"
    )


def test_work_rejects_plain_plan_tier(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        plan = proj.create("Plain plan", IssueType.PLAN, tier=BeadTier.PLAN)

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(plan.id, yes=True))
    assert excinfo.value.code == 1
    assert "only applies to epic plan beads" in capsys.readouterr().err


def test_work_plain_plan_tier_json_error_is_one_envelope(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        plan = proj.create("Plain plan", IssueType.PLAN, tier=BeadTier.PLAN)

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(plan.id, json_output=True))

    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "ok": False,
        "mode": "bead_id",
        "epic_id": plan.id,
        "error": (
            f"sase bead work only applies to epic plan beads (got plan for {plan.id})"
        ),
    }


def test_bead_id_launch_uses_epic_lock_and_reports_only_phase_children(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        epic = proj.create("Parent epic", IssueType.PLAN, tier=BeadTier.EPIC)
        phase = proj.create("Real phase", IssueType.PHASE, parent_id=epic.id)
        proj.create(
            "Nested epic",
            IssueType.PLAN,
            parent_id=epic.id,
            tier=BeadTier.EPIC,
        )

    lock_depth = 0
    lock_roots: list[Path] = []

    @contextmanager
    def fake_launch_lock(repo_root: Path):
        nonlocal lock_depth
        lock_roots.append(repo_root)
        lock_depth += 1
        try:
            yield
        finally:
            lock_depth -= 1

    def fake_launch(*_args: object, **_kwargs: object) -> bool:
        assert lock_depth == 1
        return True

    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan_store.epic_plan_launch_lock",
        fake_launch_lock,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_epic_bead_work",
        fake_launch,
    )

    bead_cli.handle_bead_work(make_args(epic.id, json_output=True))

    payload = json.loads(capsys.readouterr().out)
    assert payload["phase_bead_ids"] == [phase.id]
    assert lock_roots == [project_dir]
