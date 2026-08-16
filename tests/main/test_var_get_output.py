"""Handler tests for ``sase var get`` output formats, limits, and color."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.project_display_names import (
    ProjectDisplaySnapshot,
    ProjectRefDisplaySnapshot,
)
from tests.main.var_get_helpers import run_var_get, seed_var_get_history


def test_get_limits_visibility_and_project_display(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed_var_get_history(tmp_path, monkeypatch)
    snapshot = ProjectRefDisplaySnapshot(
        display_snapshot=ProjectDisplaySnapshot({"gh_acme__widgets": "widgets"}),
        aliases={"wid": "gh_acme__widgets"},
    )
    monkeypatch.setattr(
        "sase.main.var_cli.load_project_ref_display_snapshot",
        lambda projects_root=None: snapshot,
    )

    with pytest.raises(SystemExit) as exc:
        run_var_get(["*.status", "--format", "json", "--limit", "2"])
    assert exc.value.code == 0
    limited = json.loads(capsys.readouterr().out)
    assert limited["limits"]["matches"]["truncated"] is True
    assert limited["limits"]["matches"]["returned_count"] == 2
    assert "\x1b[" not in json.dumps(limited)

    with pytest.raises(SystemExit) as exc:
        run_var_get(["*.status", "--hidden", "--format", "json", "--limit", "0"])
    assert exc.value.code == 0
    hidden = json.loads(capsys.readouterr().out)
    assert any(item["value"] == "hidden-other" for item in hidden["matches"])

    with pytest.raises(SystemExit) as exc:
        run_var_get(
            [
                "build.status",
                "--project",
                "widgets",
                "--format",
                "json",
            ]
        )
    assert exc.value.code == 0
    named = json.loads(capsys.readouterr().out)
    assert named["query"]["projects"] == ["widgets"]
    assert named["matches"][0]["project_name"] == "widgets"
    assert named["matches"][0]["value"] == "ok"


def test_get_jsonl_and_color_modes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed_var_get_history(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        run_var_get(
            [
                "deploy.status",
                "--format",
                "jsonl",
            ]
        )
    assert exc.value.code == 0
    line = json.loads(capsys.readouterr().out)
    assert line["selector"] == "deploy.status"
    assert line["value"] == "failed"
    assert line["schema_version"] == 1

    with pytest.raises(SystemExit) as exc:
        run_var_get(["deploy.status", "--color", "always"])
    assert exc.value.code == 0
    assert "\x1b[" in capsys.readouterr().out


def test_get_raw_non_string_is_canonical_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed_var_get_history(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        run_var_get(
            [
                "build.count",
                "--project",
                "gh_acme__widgets",
                "--format",
                "raw",
            ]
        )
    assert exc.value.code == 0
    assert capsys.readouterr().out == "1\n"
