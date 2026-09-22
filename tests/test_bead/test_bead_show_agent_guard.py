"""Agent guard for ``sase bead show`` (refuse agents to ``read``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.artifact_read_log import read_artifact_read_events
from sase.bead import cli as bead_cli
from sase.bead import cli_query
from sase.bead.bead_views import SASE_BEAD_SKIP_VIEW_LOG, bead_views_log_path
from sase.main.parser import create_parser
from tests._conftest_environment import redirect_sase_home


def _stub_agent(monkeypatch: pytest.MonkeyPatch, name: str | None) -> None:
    import sase.bead.attribution as attribution

    monkeypatch.setattr(attribution, "acting_agent_name", lambda: name)


def _project() -> str:
    from sase.main.init_memory.config import project_memory_name
    from sase.project_aliases import resolve_project_alias_ref

    return resolve_project_alias_ref(project_memory_name(Path.cwd()))


def test_show_refuses_agent_and_writes_nothing(
    nested_store: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    _stub_agent(monkeypatch, "tester.host.0oa")
    monkeypatch.delenv(SASE_BEAD_SKIP_VIEW_LOG, raising=False)
    project = _project()
    issue = nested_store["phase"]
    args = create_parser().parse_args(
        ["bead", "show", issue.id, "--no-links", "--pager", "never"]
    )
    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_show(args)
    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"sase bead read {issue.id}" in captured.err
    assert "-r" in captured.err
    assert not bead_views_log_path(project).exists()
    assert list(read_artifact_read_events(project=project)) == []


def test_show_suggestion_preserves_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    _stub_agent(monkeypatch, "tester.host.0oa")
    monkeypatch.delenv(SASE_BEAD_SKIP_VIEW_LOG, raising=False)
    args = create_parser().parse_args(
        ["bead", "show", "sase-64", "-f", "json", "--no-links", "--pager", "never"]
    )
    argv = ["bead", "show", "sase-64", "-f", "json", "--no-links"]
    with pytest.raises(SystemExit) as excinfo:
        cli_query._refuse_agent_bead_show(args, argv=argv)
    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "sase bead read sase-64" in captured.err
    assert "-f" in captured.err
    assert "json" in captured.err
    assert "--no-links" in captured.err
    assert "-r" in captured.err


def test_show_falls_back_to_ids_without_show_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    _stub_agent(monkeypatch, "tester.host.0oa")
    monkeypatch.delenv(SASE_BEAD_SKIP_VIEW_LOG, raising=False)
    args = create_parser().parse_args(
        ["bead", "show", "sase-64", "--no-links", "--pager", "never"]
    )
    with pytest.raises(SystemExit) as excinfo:
        cli_query._refuse_agent_bead_show(args, argv=["bead", "list"])
    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "sase bead read sase-64" in captured.err
    assert "-r" in captured.err


def test_show_without_agent_identity_prints_normally(
    nested_store: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    _stub_agent(monkeypatch, None)
    monkeypatch.delenv(SASE_BEAD_SKIP_VIEW_LOG, raising=False)
    issue = nested_store["phase"]
    args = create_parser().parse_args(
        ["bead", "show", issue.id, "--no-links", "--pager", "never"]
    )
    bead_cli.handle_bead_show(args)
    captured = capsys.readouterr()
    assert captured.out != ""


def test_read_with_agent_identity_never_refused(
    nested_store: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    _stub_agent(monkeypatch, "tester.host.0oa")
    monkeypatch.delenv(SASE_BEAD_SKIP_VIEW_LOG, raising=False)
    project = _project()
    issue = nested_store["phase"]
    args = create_parser().parse_args(
        ["bead", "read", issue.id, "--no-links", "--pager", "never", "-r", "Need it"]
    )
    bead_cli.handle_bead_read(args)
    captured = capsys.readouterr()
    assert captured.out != ""
    rows = list(read_artifact_read_events(project=project))
    assert [row.ref for row in rows] == [f"bead:{issue.id}"]
