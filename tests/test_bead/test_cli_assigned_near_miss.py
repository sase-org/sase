"""CLI coverage for assigned-bead one-segment near-miss warnings and refusals."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.assigned_near_miss import _near_miss_banner
from sase.bead.model import BeadTier, IssueType, Status
from sase.bead.project import BeadProject
from sase.bead.work_types import SASE_BEAD_ID_ENV, SASE_PHASE_BEAD_ID_ENV
from sase.main.parser import create_parser
from tests._conftest_environment import redirect_sase_home


def _seed_near_miss_tree(project_dir: Path) -> tuple[str, str, str, str]:
    """Return ``(assigned, near_miss, sibling, parent)`` full IDs.

    ``assigned`` is ``<epic>.1.2.1``; ``near_miss`` is ``<epic>.1.1``.
    """
    with BeadProject(project_dir) as project:
        epic = project.create("Epic", IssueType.PLAN, tier=BeadTier.EPIC)
        first = project.create("First", IssueType.PHASE, parent_id=epic.id)
        near = project.create("Near", IssueType.PHASE, parent_id=first.id)
        second = project.create("Second", IssueType.PHASE, parent_id=first.id)
        assigned = project.create("Assigned", IssueType.PHASE, parent_id=second.id)
        sibling = project.create("Sibling", IssueType.PHASE, parent_id=second.id)
    return assigned.id, near.id, sibling.id, second.id


def _assign(monkeypatch: pytest.MonkeyPatch, bead_id: str) -> None:
    monkeypatch.delenv(SASE_PHASE_BEAD_ID_ENV, raising=False)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    monkeypatch.setenv(SASE_BEAD_ID_ENV, bead_id)


def _clear_assigned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(SASE_PHASE_BEAD_ID_ENV, raising=False)
    monkeypatch.delenv(SASE_BEAD_ID_ENV, raising=False)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)


def _store_snapshot(project_dir: Path) -> dict[str, bytes]:
    beads_dir = project_dir / "sdd" / "beads"
    return {
        str(path.relative_to(beads_dir)): path.read_bytes()
        for path in beads_dir.rglob("*")
        if path.is_file()
    }


def _read_args(*argv: str):
    return create_parser().parse_args(["bead", "read", *argv])


def test_read_banners_text_top_and_bottom(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    assigned, near, _sibling, _parent = _seed_near_miss_tree(project_dir)
    _assign(monkeypatch, assigned)
    banner = _near_miss_banner(near, assigned)

    bead_cli.handle_bead_read(
        _read_args(near, "--no-links", "--pager", "never", "-r", "Need it")
    )
    captured = capsys.readouterr()
    assert captured.out.startswith(banner)
    assert captured.out.rstrip().endswith(banner)
    assert captured.out.count("differ by one segment") == 2


def test_read_json_warns_on_stderr_and_keeps_stdout(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    assigned, near, _sibling, _parent = _seed_near_miss_tree(project_dir)
    _assign(monkeypatch, assigned)

    bead_cli.handle_bead_read(
        _read_args(
            near,
            "--format",
            "json",
            "--no-links",
            "--pager",
            "never",
            "-r",
            "Need it",
        )
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["issue"]["id"] == near
    assert _near_miss_banner(near, assigned) in captured.err
    assert "⚠" not in captured.out


def test_read_missing_near_miss_suggests_assigned(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    assigned, _near, _sibling, _parent = _seed_near_miss_tree(project_dir)
    _assign(monkeypatch, assigned)
    # assigned is ``<root>.1.2.1``; ``<root>.2.1`` deletes the first ``1``.
    root = assigned.split(".", 1)[0]
    missing = f"{root}.2.1"

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_read(
            _read_args(missing, "--no-links", "--pager", "never", "-r", "Need it")
        )
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert f"issue not found: {missing}" in err
    assert f"did you mean `{assigned}`?" in err


def test_note_update_and_epic_symbols_warn_on_stderr(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assigned, near, _sibling, _parent = _seed_near_miss_tree(project_dir)
    _assign(monkeypatch, assigned)
    banner = _near_miss_banner(near, assigned)

    bead_cli.handle_bead_note(
        create_parser().parse_args(["bead", "note", near, "progress"])
    )
    note_err = capsys.readouterr().err
    assert banner in note_err

    bead_cli.handle_bead_update(
        create_parser().parse_args(["bead", "update", near, "--title", "Renamed"])
    )
    update_captured = capsys.readouterr()
    assert banner in update_captured.err
    assert "Updated issue:" in update_captured.out

    bead_cli.handle_bead_epic_symbols(
        create_parser().parse_args(["bead", "epic-symbols", near, "--color", "never"])
    )
    symbols_err = capsys.readouterr().err
    assert banner in symbols_err


def test_close_and_open_refuse_before_write(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assigned, near, _sibling, _parent = _seed_near_miss_tree(project_dir)
    _assign(monkeypatch, assigned)
    before = _store_snapshot(project_dir)

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_close(create_parser().parse_args(["bead", "close", near]))
    assert excinfo.value.code == 1
    close_err = capsys.readouterr().err
    assert f"`{near}` is not your assigned bead `{assigned}`" in close_err
    assert "differs from the assigned bead by one segment" in close_err
    assert _store_snapshot(project_dir) == before

    with BeadProject(project_dir) as project:
        project.close([near], reason="park")
    closed_snapshot = _store_snapshot(project_dir)

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_open(create_parser().parse_args(["bead", "open", near]))
    assert excinfo.value.code == 1
    open_err = capsys.readouterr().err
    assert f"`{near}` is not your assigned bead `{assigned}`" in open_err
    assert "differs from the assigned bead by one segment" in open_err
    assert _store_snapshot(project_dir) == closed_snapshot
    with BeadProject(project_dir) as project:
        assert project.show(near).status is Status.CLOSED


def test_no_effect_without_assigned_bead(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    _assigned, near, sibling, _parent = _seed_near_miss_tree(project_dir)
    _clear_assigned(monkeypatch)

    bead_cli.handle_bead_read(
        _read_args(near, "--no-links", "--pager", "never", "-r", "Need it")
    )
    read_out = capsys.readouterr()
    assert "differ by one segment" not in read_out.out
    assert "differ by one segment" not in read_out.err

    bead_cli.handle_bead_close(create_parser().parse_args(["bead", "close", near]))
    close_out = capsys.readouterr()
    assert "Closed" in close_out.out
    assert "one segment" not in close_out.err
    with BeadProject(project_dir) as project:
        assert project.show(near).status is Status.CLOSED

    bead_cli.handle_bead_read(
        _read_args(sibling, "--no-links", "--pager", "never", "-r", "Need it")
    )
    sibling_out = capsys.readouterr()
    assert sibling in sibling_out.out


def test_assigned_bead_and_relatives_are_not_near_misses(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    assigned, _near, sibling, parent = _seed_near_miss_tree(project_dir)
    _assign(monkeypatch, assigned)

    for target in (assigned, sibling, parent):
        bead_cli.handle_bead_read(
            _read_args(target, "--no-links", "--pager", "never", "-r", "Need it")
        )
        captured = capsys.readouterr()
        assert "differ by one segment" not in captured.out
        assert "differ by one segment" not in captured.err

    bead_cli.handle_bead_close(create_parser().parse_args(["bead", "close", assigned]))
    close_out = capsys.readouterr()
    assert "Closed" in close_out.out
    assert "one segment" not in close_out.err
