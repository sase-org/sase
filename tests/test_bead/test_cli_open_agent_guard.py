"""Agent guard for ``sase bead open`` (refuse agents to ``read``)."""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import IssueType, Status
from sase.bead.project import BeadProject
from sase.main import bead_fast_path


@pytest.fixture
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    with BeadProject.init(tmp_path):
        pass
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sase.bead.workspace.resolve_primary_workspace", lambda: None)
    yield tmp_path


def _stub_agent(monkeypatch: pytest.MonkeyPatch, name: str | None) -> None:
    import sase.bead.attribution as attribution

    monkeypatch.setattr(attribution, "acting_agent_name", lambda: name)


def _make_bead(project_dir: Path, status: Status) -> str:
    with BeadProject(project_dir) as proj:
        issue = proj.create("Guarded bead", IssueType.PLAN)
        if status is Status.CLOSED:
            proj.close([issue.id], reason="done")
        elif status is not Status.OPEN:
            proj.update(issue.id, status=status.value)
        return issue.id


def _status_of(project_dir: Path, issue_id: str) -> Status:
    with BeadProject(project_dir) as proj:
        return proj.show(issue_id).status


def test_slow_path_refuses_agent_open_of_in_progress_bead(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue_id = _make_bead(project_dir, Status.IN_PROGRESS)
    _stub_agent(monkeypatch, "tester.host.0oa")

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_open(argparse.Namespace(id=issue_id))

    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "reopens a closed bead" in captured.err
    assert f"sase bead read {issue_id}" in captured.err
    assert "-r" in captured.err
    assert _status_of(project_dir, issue_id) is Status.IN_PROGRESS


def test_slow_path_refuses_agent_open_of_open_bead(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue_id = _make_bead(project_dir, Status.OPEN)
    _stub_agent(monkeypatch, "tester.host.0oa")

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_open(argparse.Namespace(id=issue_id))

    assert excinfo.value.code == 2
    assert "reopens a closed bead" in capsys.readouterr().err
    assert _status_of(project_dir, issue_id) is Status.OPEN


def test_slow_path_allows_agent_open_of_closed_bead(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue_id = _make_bead(project_dir, Status.CLOSED)
    _stub_agent(monkeypatch, "tester.host.0oa")

    bead_cli.handle_bead_open(argparse.Namespace(id=issue_id))

    assert _status_of(project_dir, issue_id) is Status.OPEN
    assert f"○ Opened: {issue_id}" in capsys.readouterr().out


def test_slow_path_allows_human_open_of_non_closed_bead(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue_id = _make_bead(project_dir, Status.IN_PROGRESS)
    _stub_agent(monkeypatch, None)

    bead_cli.handle_bead_open(argparse.Namespace(id=issue_id))

    assert _status_of(project_dir, issue_id) is Status.OPEN
    assert f"○ Opened: {issue_id}" in capsys.readouterr().out


def test_slow_path_missing_bead_with_agent_reports_not_found(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _stub_agent(monkeypatch, "tester.host.0oa")

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_open(argparse.Namespace(id="beads-missing"))

    assert excinfo.value.code == 1
    assert capsys.readouterr().err == "Error: issue not found: beads-missing\n"


def test_fast_path_refuses_agent_open_of_non_closed_bead(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue_id = _make_bead(project_dir, Status.IN_PROGRESS)
    _stub_agent(monkeypatch, "tester.host.0oa")

    with pytest.raises(SystemExit) as excinfo:
        bead_fast_path.execute_bead_cli(["open", issue_id])

    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "reopens a closed bead" in captured.err
    assert f"sase bead read {issue_id}" in captured.err
    assert "-r" in captured.err
    assert _status_of(project_dir, issue_id) is Status.IN_PROGRESS


def test_fast_path_allows_agent_open_of_closed_bead(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue_id = _make_bead(project_dir, Status.CLOSED)
    _stub_agent(monkeypatch, "tester.host.0oa")
    monkeypatch.setattr(
        bead_fast_path,
        "_apply_mutation_side_effects",
        lambda _beads_dir, _summary, **_kwargs: True,
    )
    monkeypatch.setattr("sase.bead.sync.schedule_bead_refresh", lambda _beads_dir: None)

    assert bead_fast_path.execute_bead_cli(["open", issue_id]) == 0
    assert _status_of(project_dir, issue_id) is Status.OPEN


def test_fast_path_allows_human_open_of_non_closed_bead(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue_id = _make_bead(project_dir, Status.IN_PROGRESS)
    _stub_agent(monkeypatch, None)
    monkeypatch.setattr(
        bead_fast_path,
        "_apply_mutation_side_effects",
        lambda _beads_dir, _summary, **_kwargs: True,
    )
    monkeypatch.setattr("sase.bead.sync.schedule_bead_refresh", lambda _beads_dir: None)

    assert bead_fast_path.execute_bead_cli(["open", issue_id]) == 0
    assert _status_of(project_dir, issue_id) is Status.OPEN
