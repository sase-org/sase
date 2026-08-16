"""Handler tests for ``sase var get`` snapshot mode (current run and ``<agent>``)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.main.var_cli_helpers import (
    isolate_sase_home,
    rebuild_home_index,
    write_indexed_agent,
)
from tests.main.var_get_helpers import (
    run_var_get,
    seed_var_get_history,
    write_current_artifacts,
)


def test_get_reads_current_artifacts_even_when_index_is_stale(
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
        run_var_get(["--format", "json", "--color", "never"])

    assert exc.value.code == 0
    assert capsys.readouterr().out == '{"status":"fresh"}\n'


def test_get_named_agent_uses_newest_visible_artifact(
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
        run_var_get(["<build>", "--format", "json"])

    assert exc.value.code == 0
    assert json.loads(capsys.readouterr().out) == {
        "notes": "line one\nline two",
        "status": "new",
    }

    with pytest.raises(SystemExit) as exc:
        run_var_get(["<build>", "--hidden", "--format", "json"])
    assert exc.value.code == 0
    assert json.loads(capsys.readouterr().out) == {"status": "hidden"}


def test_get_named_agent_repeatable_project_filter_and_unknown_error(
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
        run_var_get(["<build>", "--project", "alpha", "--format", "json"])
    assert exc.value.code == 0
    assert json.loads(capsys.readouterr().out) == {"where": "alpha"}

    with pytest.raises(SystemExit) as exc:
        run_var_get(
            [
                "<build>",
                "--project",
                "alpha",
                "--project",
                "beta",
                "--format",
                "json",
            ]
        )
    assert exc.value.code == 0
    assert json.loads(capsys.readouterr().out) == {"where": "beta"}

    with pytest.raises(SystemExit) as exc:
        run_var_get(["<missing>", "--project", "alpha"])
    assert exc.value.code == 1
    assert "unknown agent: missing (project alpha)" in capsys.readouterr().err

    with pytest.raises(SystemExit) as exc:
        run_var_get(["<missing>", "--project", "alpha", "--project", "beta"])
    assert exc.value.code == 1
    assert "unknown agent: missing (projects alpha, beta)" in capsys.readouterr().err


def test_get_preserves_dotted_hyphenated_and_digit_snapshot_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed_var_get_history(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        run_var_get(["<research.foo>", "--format", "json"])
    assert exc.value.code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "member"

    with pytest.raises(SystemExit) as exc:
        run_var_get(["<research.foo-bar>", "--format", "json"])
    assert exc.value.code == 0
    assert json.loads(capsys.readouterr().out) == {"status": "hyphen"}

    with pytest.raises(SystemExit) as exc:
        run_var_get(["<2review>", "--format", "json"])
    assert exc.value.code == 0
    assert json.loads(capsys.readouterr().out) == {"status": "digit"}


def test_get_known_agent_without_variables_is_empty_success(
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
        run_var_get(["<empty>", "--color", "never"])

    assert exc.value.code == 0
    assert capsys.readouterr().out == "No output variables set.\n"


def test_get_current_requires_artifacts_dir(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)

    with pytest.raises(SystemExit) as exc:
        run_var_get([])

    assert exc.value.code == 1
    assert "SASE_ARTIFACTS_DIR or a quoted <agent_name>" in capsys.readouterr().err


def test_get_snapshot_color_never_has_no_ansi(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_current_artifacts(tmp_path, monkeypatch, {"status": "ok"})

    with pytest.raises(SystemExit) as exc:
        run_var_get(["--color", "never"])

    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert output == "status: ok\n"
    assert "\x1b[" not in output


@pytest.mark.parametrize("fmt", ["raw", "jsonl"])
def test_get_snapshot_rejects_selector_only_formats(
    fmt: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_current_artifacts(tmp_path, monkeypatch, {"status": "ok"})

    with pytest.raises(SystemExit) as exc:
        run_var_get(["--format", fmt])
    assert exc.value.code == 2
    assert f"--format {fmt} is only valid with a selector" in capsys.readouterr().err

    home, projects = isolate_sase_home(tmp_path, monkeypatch)
    write_indexed_agent(
        projects,
        project="proj",
        timestamp="20260814101010",
        name="build",
        variables={"status": "ok"},
    )
    rebuild_home_index(home, projects)
    with pytest.raises(SystemExit) as exc:
        run_var_get(["<build>", "--format", fmt])
    assert exc.value.code == 2
    assert "build.*" in capsys.readouterr().err


def test_get_snapshot_rejects_explicit_selector_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_current_artifacts(tmp_path, monkeypatch, {"status": "ok"})

    with pytest.raises(SystemExit) as exc:
        run_var_get(["--limit", "5"])
    assert exc.value.code == 2
    assert "--limit applies only to selector" in capsys.readouterr().err

    home, projects = isolate_sase_home(tmp_path, monkeypatch)
    write_indexed_agent(
        projects,
        project="proj",
        timestamp="20260814101010",
        name="build",
        variables={"status": "ok"},
    )
    rebuild_home_index(home, projects)
    with pytest.raises(SystemExit) as exc:
        run_var_get(["<build>", "--limit", "0"])
    assert exc.value.code == 2
    assert "build.*" in capsys.readouterr().err


def test_get_wrapped_snapshot_is_not_selector_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed_var_get_history(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        run_var_get(["<build>", "--project", "gh_acme__widgets", "--format", "json"])
    assert exc.value.code == 0
    snapshot = json.loads(capsys.readouterr().out)
    assert snapshot == {
        "count": 1,
        "report": {"nested": {"n": 2}, "summary": "fresh"},
        "results": ["x", "y"],
        "status": "ok",
    }
    assert "matches" not in snapshot

    with pytest.raises(SystemExit) as exc:
        run_var_get(
            [
                "build.*",
                "--project",
                "gh_acme__widgets",
                "--format",
                "json",
                "--limit",
                "0",
            ]
        )
    assert exc.value.code == 0
    selected = json.loads(capsys.readouterr().out)
    assert "matches" in selected
    assert selected["schema_version"] == 1
