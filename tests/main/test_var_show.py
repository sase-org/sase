"""Handler tests for ``sase var show``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.main.parser import create_parser
from sase.main.var_cli import resolve_current_var_agent_name
from sase.main.var_handler import handle_var_command
from tests.main.var_cli_helpers import (
    isolate_sase_home,
    rebuild_home_index,
    write_indexed_agent,
)


def _run_show(argv: list[str]) -> None:
    handle_var_command(create_parser().parse_args(["var", "show", *argv]))


def test_show_reads_current_artifacts_even_when_index_is_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home, projects = isolate_sase_home(tmp_path, monkeypatch)
    artifact = write_indexed_agent(
        projects,
        project="proj",
        timestamp="20260814101010",
        name="writer",
        variables={"status": "old"},
    )
    rebuild_home_index(home, projects)
    (artifact / "agent_meta.json").write_text(
        json.dumps({"name": "writer", "output_variables": {"status": "fresh"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifact))

    with pytest.raises(SystemExit) as exc:
        _run_show(["--format", "json", "--color", "never"])

    assert exc.value.code == 0
    assert capsys.readouterr().out == '{"status":"fresh"}\n'


def test_show_named_agent_uses_newest_visible_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home, projects = isolate_sase_home(tmp_path, monkeypatch)
    write_indexed_agent(
        projects,
        project="proj",
        timestamp="20260814101010",
        name="build",
        variables={"status": "old"},
    )
    write_indexed_agent(
        projects,
        project="proj",
        timestamp="20260814121212",
        name="build",
        variables={"status": "new", "notes": "line one\nline two"},
    )
    write_indexed_agent(
        projects,
        project="proj",
        timestamp="20260814131313",
        name="build",
        variables={"status": "hidden"},
        hidden=True,
    )
    rebuild_home_index(home, projects)

    with pytest.raises(SystemExit) as exc:
        _run_show(["build", "--format", "json"])

    assert exc.value.code == 0
    assert json.loads(capsys.readouterr().out) == {
        "notes": "line one\nline two",
        "status": "new",
    }


def test_show_named_agent_project_filter_and_unknown_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home, projects = isolate_sase_home(tmp_path, monkeypatch)
    write_indexed_agent(
        projects,
        project="alpha",
        timestamp="20260814101010",
        name="build",
        variables={"where": "alpha"},
    )
    write_indexed_agent(
        projects,
        project="beta",
        timestamp="20260814111111",
        name="build",
        variables={"where": "beta"},
    )
    rebuild_home_index(home, projects)

    with pytest.raises(SystemExit) as exc:
        _run_show(["build", "--project", "alpha", "--format", "json"])
    assert exc.value.code == 0
    assert json.loads(capsys.readouterr().out) == {"where": "alpha"}

    with pytest.raises(SystemExit) as exc:
        _run_show(["missing", "--project", "alpha"])
    assert exc.value.code == 1
    assert "unknown agent: missing (project alpha)" in capsys.readouterr().err


def test_show_known_agent_without_variables_is_empty_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home, projects = isolate_sase_home(tmp_path, monkeypatch)
    write_indexed_agent(
        projects,
        project="proj",
        timestamp="20260814101010",
        name="empty",
        variables=None,
    )
    rebuild_home_index(home, projects)

    with pytest.raises(SystemExit) as exc:
        _run_show(["empty", "--color", "never"])

    assert exc.value.code == 0
    assert capsys.readouterr().out == "No output variables set.\n"


def test_show_current_requires_artifacts_dir(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)

    with pytest.raises(SystemExit) as exc:
        _run_show([])

    assert exc.value.code == 1
    assert "SASE_ARTIFACTS_DIR or an AGENT_NAME" in capsys.readouterr().err


def test_current_identity_prefers_meta_then_name_then_nonsentinel_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"name": "from-meta"}),
        encoding="utf-8",
    )

    assert (
        resolve_current_var_agent_name(
            str(artifacts),
            {"SASE_ARTIFACTS_DIR": str(artifacts), "SASE_AGENT": "1"},
        )
        == "from-meta"
    )
    assert (
        resolve_current_var_agent_name(
            str(artifacts),
            {
                "SASE_ARTIFACTS_DIR": str(artifacts),
                "SASE_AGENT_NAME": "from-env",
                "SASE_AGENT": "1",
            },
        )
        == "from-meta"
    )
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "agent_meta.json").write_text("{}", encoding="utf-8")
    assert (
        resolve_current_var_agent_name(
            str(empty),
            {"SASE_ARTIFACTS_DIR": str(empty), "SASE_AGENT_NAME": "from-env"},
        )
        == "from-env"
    )
    assert (
        resolve_current_var_agent_name(
            str(empty),
            {"SASE_ARTIFACTS_DIR": str(empty), "SASE_AGENT": "legacy-name"},
        )
        == "legacy-name"
    )
    assert (
        resolve_current_var_agent_name(
            str(empty),
            {"SASE_ARTIFACTS_DIR": str(empty), "SASE_AGENT": "1"},
        )
        is None
    )


def test_show_color_never_has_no_ansi(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"output_variables": {"status": "ok"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))

    with pytest.raises(SystemExit) as exc:
        _run_show(["--color", "never"])

    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert output == "status: ok\n"
    assert "\x1b[" not in output
