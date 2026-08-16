"""Handler tests for ``sase var get`` selector resolution and match ordering."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.main.var_get_helpers import run_var_get, seed_var_get_history


def test_get_unscoped_and_exact_selectors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed_var_get_history(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        run_var_get(["status", "--format", "json", "--color", "never"])
    assert exc.value.code == 0
    newest = json.loads(capsys.readouterr().out)
    assert newest["schema_version"] == 1
    assert newest["matches"][0]["value"] == "failed"
    assert newest["matches"][0]["agent_name"] == "deploy"

    with pytest.raises(SystemExit) as exc:
        run_var_get(
            [
                "build.status",
                "--project",
                "gh_acme__widgets",
                "--format",
                "raw",
            ]
        )
    assert exc.value.code == 0
    assert capsys.readouterr().out == "ok\n"


def test_get_pretty_attributes_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed_var_get_history(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        run_var_get(
            [
                "2review.status",
                "--color",
                "never",
            ]
        )
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert output.startswith("digit\n")
    assert "  2review · other · 20260815171717 · status" not in output
    assert "  2review · gh_acme__widgets · 20260815171717 · status" in output


def test_get_dotted_hyphenated_digit_and_hood_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed_var_get_history(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        run_var_get(
            [
                'research.foo.report["summary"]',
                "research.foo-bar.status",
                "2review.status",
                "--format",
                "json",
            ]
        )
    assert exc.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert [item["value"] for item in payload["matches"]] == [
        "from-foo",
        "hyphen",
        "digit",
    ]

    with pytest.raises(SystemExit) as exc:
        run_var_get(["research.*.status", "--format", "json", "--limit", "0"])
    assert exc.value.code == 0
    hood = json.loads(capsys.readouterr().out)
    assert [item["agent_name"] for item in hood["matches"]] == [
        "research.foo-bar",
        "research.foo",
        "research",
    ]


def test_get_global_and_key_wildcards_and_repeated_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed_var_get_history(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        run_var_get(["*.status", "--format", "json", "--limit", "0"])
    assert exc.value.code == 0
    global_status = json.loads(capsys.readouterr().out)
    build_matches = [
        item for item in global_status["matches"] if item["agent_name"] == "build"
    ]
    assert len(build_matches) == 1
    assert build_matches[0]["value"] == "ok"
    assert all(item["agent_name"] for item in global_status["matches"])

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
    keys = json.loads(capsys.readouterr().out)
    assert [item["key"] for item in keys["matches"]] == [
        "count",
        "report",
        "results",
        "status",
    ]
    assert {item["timestamp"] for item in keys["matches"]} == {"20260815121212"}


def test_get_multiple_selectors_dedup_and_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed_var_get_history(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        run_var_get(
            [
                "deploy.status",
                "status",
                "2review.status",
                "--format",
                "json",
            ]
        )
    assert exc.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert [item["selector"] for item in payload["matches"]] == [
        "deploy.status",
        "2review.status",
    ]


def test_get_nested_paths_and_escaped_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed_var_get_history(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        run_var_get(
            [
                "build.results[0]",
                'build.report["nested"]["n"]',
                "--project",
                "gh_acme__widgets",
                "--format",
                "json",
            ]
        )
    assert exc.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert [item["value"] for item in payload["matches"]] == ["x", 2]
