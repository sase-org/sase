"""Handler tests for historical ``sase var list``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.main.var_handler import handle_var_command
from tests.main.parser_cli_helpers import parse_sase_args
from sase.project_display_names import (
    ProjectDisplaySnapshot,
    ProjectRefDisplaySnapshot,
)
from tests.main.var_cli_helpers import (
    isolate_sase_home,
    rebuild_home_index,
    write_indexed_agent,
)


def _run_list(argv: list[str]) -> None:
    handle_var_command(parse_sase_args(["var", "list", *argv]))


def _seed_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home, projects = isolate_sase_home(tmp_path, monkeypatch)
    write_indexed_agent(
        projects,
        project="gh_acme__widgets",
        timestamp="20260814101010",
        name="build",
        variables={
            "status": "ok",
            "count": 1,
            "report": {"z": 2, "a": 1},
            "notes": "Snowman ☃\nnext",
        },
    )
    write_indexed_agent(
        projects,
        project="gh_acme__widgets",
        timestamp="20260814111111",
        name="build.worker",
        variables={"status": "ok", "count": 1.0},
        hidden=True,
    )
    write_indexed_agent(
        projects,
        project="other",
        timestamp="20260815121212",
        name="deploy",
        variables={"status": "failed", "result": ["a", "b"]},
    )
    write_indexed_agent(
        projects,
        project="gh_acme__widgets",
        timestamp="20260810100000",
        name="build",
        variables={"status": "ok"},
    )
    rebuild_home_index(home, projects)
    return home


def test_list_pretty_groups_values_and_marks_truncation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_history(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        _run_list(["--color", "never", "--key", "status", "--limit", "1:1"])

    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert output.startswith("status\n")
    assert "3 occurrences · 2 values" in output
    assert "failed" in output
    assert "×1" in output
    assert "deploy" in output
    assert "… 1 more value (limit 1)" in output
    assert "ok" not in output

    with pytest.raises(SystemExit) as exc:
        _run_list(["--color", "never", "--limit", "1:5"])
    assert exc.value.code == 0
    truncated_keys = capsys.readouterr().out
    assert truncated_keys.startswith("result\n")
    assert "… 4 more keys (limit 1)" in truncated_keys
    assert "status" not in truncated_keys.split("… 4 more keys", 1)[0]


def test_list_json_envelope_and_jsonl_are_stable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_history(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        _run_list(["--format", "json", "--key", "status", "--limit", "0"])
    assert exc.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["query"]["keys"] == ["status"]
    assert payload["query"]["key_limit"] == 0
    assert payload["limits"]["keys"]["truncated"] is False
    assert payload["groups"][0]["key"] == "status"
    assert payload["groups"][0]["distinct_value_count"] == 2
    assert [item["value"] for item in payload["groups"][0]["values"]] == [
        "failed",
        "ok",
    ]
    assert "\x1b[" not in json.dumps(payload)

    with pytest.raises(SystemExit) as exc:
        _run_list(["--format", "jsonl", "--key", "status", "--limit", "0:1"])
    assert exc.value.code == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(lines) == 1
    assert lines[0]["key"] == "status"
    assert lines[0]["value"] == "failed"
    assert lines[0]["values_limit"]["truncated"] is True


def test_list_filters_agent_hidden_value_and_dates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_history(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        _run_list(
            [
                "--format",
                "json",
                "--agent",
                "build.*",
                "--key",
                "count",
                "--hidden",
                "--limit",
                "0",
            ]
        )
    assert exc.value.code == 0
    hidden_counts = json.loads(capsys.readouterr().out)
    assert hidden_counts["groups"][0]["occurrence_count"] == 2
    assert [item["value"] for item in hidden_counts["groups"][0]["values"]] == [
        1.0,
        1,
    ]

    with pytest.raises(SystemExit) as exc:
        _run_list(
            [
                "--format",
                "json",
                "--value-json",
                '"ok"',
                "--since",
                "2026-08-14",
                "--until",
                "2026-08-14",
                "--limit",
                "0",
            ]
        )
    assert exc.value.code == 0
    dated = json.loads(capsys.readouterr().out)
    assert dated["query"]["since_timestamp"] == "20260814000000"
    assert dated["query"]["until_timestamp"] == "20260814235959"
    assert dated["groups"][0]["key"] == "status"
    assert dated["groups"][0]["occurrence_count"] == 1
    assert dated["groups"][0]["values"][0]["agents"] == ["build"]


def test_list_value_substring_and_reverse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_history(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        _run_list(["--format", "json", "--value", "snowman", "--limit", "0"])
    assert exc.value.code == 0
    snowman = json.loads(capsys.readouterr().out)
    assert snowman["groups"][0]["key"] == "notes"
    assert snowman["groups"][0]["values"][0]["value"] == "Snowman ☃\nnext"

    with pytest.raises(SystemExit) as exc:
        _run_list(
            [
                "--format",
                "json",
                "--key",
                "status",
                "--reverse",
                "--limit",
                "0",
            ]
        )
    assert exc.value.code == 0
    reversed_status = json.loads(capsys.readouterr().out)
    assert [item["value"] for item in reversed_status["groups"][0]["values"]] == [
        "ok",
        "failed",
    ]


def test_list_project_display_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_history(tmp_path, monkeypatch)
    snapshot = ProjectRefDisplaySnapshot(
        display_snapshot=ProjectDisplaySnapshot({"gh_acme__widgets": "widgets"}),
        aliases={"wid": "gh_acme__widgets"},
    )
    monkeypatch.setattr(
        "sase.main.var_cli.load_project_ref_display_snapshot",
        lambda projects_root=None: snapshot,
    )

    with pytest.raises(SystemExit) as exc:
        _run_list(
            [
                "--format",
                "json",
                "--project",
                "widgets",
                "--key",
                "status",
                "--limit",
                "0",
            ]
        )
    assert exc.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["query"]["projects"] == ["widgets"]
    assert payload["groups"][0]["values"][0]["projects"] == ["widgets"]
    assert payload["groups"][0]["values"][0]["newest"]["project_name"] == "widgets"


def test_list_empty_states_and_color_modes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_history(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        _run_list(["--key", "missing", "--color", "never"])
    assert exc.value.code == 0
    assert capsys.readouterr().out == "No matching output variables.\n"

    with pytest.raises(SystemExit) as exc:
        _run_list(["--key", "status", "--color", "always", "--limit", "1:1"])
    assert exc.value.code == 0
    colored = capsys.readouterr().out
    assert "\x1b[" in colored

    with pytest.raises(SystemExit) as exc:
        _run_list(["--format", "json", "--color", "always", "--key", "status"])
    assert exc.value.code == 0
    assert "\x1b[" not in capsys.readouterr().out


def test_list_does_not_require_agent_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_history(tmp_path, monkeypatch)
    monkeypatch.delenv("SASE_AGENT", raising=False)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)

    with pytest.raises(SystemExit) as exc:
        _run_list(["--format", "json", "--limit", "1"])

    assert exc.value.code == 0
    assert json.loads(capsys.readouterr().out)["groups"]
