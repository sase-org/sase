"""Handler tests for ``sase var get``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.main.parser import create_parser
from sase.main.var_handler import handle_var_command
from sase.project_display_names import (
    ProjectDisplaySnapshot,
    ProjectRefDisplaySnapshot,
)
from tests.main.var_cli_helpers import (
    isolate_sase_home,
    rebuild_home_index,
    write_indexed_agent,
)


def _run_get(argv: list[str]) -> None:
    handle_var_command(create_parser().parse_args(["var", "get", *argv]))


def _seed_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home, projects = isolate_sase_home(tmp_path, monkeypatch)
    write_indexed_agent(
        projects,
        project="gh_acme__widgets",
        timestamp="20260814101010",
        name="build",
        variables={
            "status": "old",
            "results": ["a", "b"],
            "report": {"summary": "old", 'a"b': 1},
        },
    )
    write_indexed_agent(
        projects,
        project="gh_acme__widgets",
        timestamp="20260815121212",
        name="build",
        variables={
            "status": "ok",
            "results": ["x", "y"],
            "report": {"summary": "fresh", "nested": {"n": 2}},
            "count": 1,
        },
    )
    write_indexed_agent(
        projects,
        project="gh_acme__widgets",
        timestamp="20260815131313",
        name="build.worker",
        variables={"status": "ok", "count": 1.0},
        hidden=True,
    )
    write_indexed_agent(
        projects,
        project="gh_acme__widgets",
        timestamp="20260815141414",
        name="research",
        variables={"status": "root"},
    )
    write_indexed_agent(
        projects,
        project="gh_acme__widgets",
        timestamp="20260815151515",
        name="research.foo",
        variables={"status": "member", "report": {"summary": "from-foo"}},
    )
    write_indexed_agent(
        projects,
        project="gh_acme__widgets",
        timestamp="20260815161616",
        name="research.foo-bar",
        variables={"status": "hyphen"},
    )
    write_indexed_agent(
        projects,
        project="gh_acme__widgets",
        timestamp="20260815171717",
        name="2review",
        variables={"status": "digit"},
    )
    write_indexed_agent(
        projects,
        project="other",
        timestamp="20260815181818",
        name="deploy",
        variables={"status": "failed"},
    )
    write_indexed_agent(
        projects,
        project="other",
        timestamp="20260815191919",
        name="build",
        variables={"status": "hidden-other"},
        hidden=True,
    )
    rebuild_home_index(home, projects)
    return home


def test_get_unscoped_and_exact_selectors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_history(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        _run_get(["status", "--format", "json", "--color", "never"])
    assert exc.value.code == 0
    newest = json.loads(capsys.readouterr().out)
    assert newest["schema_version"] == 1
    assert newest["matches"][0]["value"] == "failed"
    assert newest["matches"][0]["agent_name"] == "deploy"

    with pytest.raises(SystemExit) as exc:
        _run_get(
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
    _seed_history(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        _run_get(
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
    _seed_history(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        _run_get(
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
        _run_get(["research.*.status", "--format", "json", "--limit", "0"])
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
    _seed_history(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        _run_get(["*.status", "--format", "json", "--limit", "0"])
    assert exc.value.code == 0
    global_status = json.loads(capsys.readouterr().out)
    build_matches = [
        item for item in global_status["matches"] if item["agent_name"] == "build"
    ]
    assert len(build_matches) == 1
    assert build_matches[0]["value"] == "ok"
    assert all(item["agent_name"] for item in global_status["matches"])

    with pytest.raises(SystemExit) as exc:
        _run_get(
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
    _seed_history(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        _run_get(
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
    _seed_history(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        _run_get(
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


def test_get_path_and_no_match_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_history(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        _run_get(["build.status[0]", "--project", "gh_acme__widgets"])
    assert exc.value.code == 1
    assert "expected list, found string" in capsys.readouterr().err

    with pytest.raises(SystemExit) as exc:
        _run_get(['build.report["nope"]', "--project", "gh_acme__widgets"])
    assert exc.value.code == 1
    assert "missing key" in capsys.readouterr().err

    with pytest.raises(SystemExit) as exc:
        _run_get(["build.results[5]", "--project", "gh_acme__widgets"])
    assert exc.value.code == 1
    assert "out of range" in capsys.readouterr().err

    with pytest.raises(SystemExit) as exc:
        _run_get(["missing.status"])
    assert exc.value.code == 1
    assert "no match for selector 'missing.status'" in capsys.readouterr().err


def test_get_raw_requires_one_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_history(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        _run_get(["*.status", "--format", "raw", "--limit", "0"])
    assert exc.value.code == 1
    assert "exactly one resolved value" in capsys.readouterr().err

    with pytest.raises(SystemExit) as exc:
        _run_get(["*.status", "--format", "raw", "--limit", "1"])
    assert exc.value.code == 1
    assert "exactly one resolved value" in capsys.readouterr().err


def test_get_limits_visibility_and_project_display(
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
        _run_get(["*.status", "--format", "json", "--limit", "2"])
    assert exc.value.code == 0
    limited = json.loads(capsys.readouterr().out)
    assert limited["limits"]["matches"]["truncated"] is True
    assert limited["limits"]["matches"]["returned_count"] == 2
    assert "\x1b[" not in json.dumps(limited)

    with pytest.raises(SystemExit) as exc:
        _run_get(["*.status", "--hidden", "--format", "json", "--limit", "0"])
    assert exc.value.code == 0
    hidden = json.loads(capsys.readouterr().out)
    assert any(item["value"] == "hidden-other" for item in hidden["matches"])

    with pytest.raises(SystemExit) as exc:
        _run_get(
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


def test_get_ambiguous_project_is_a_query_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_history(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        _run_get(["build.status", "--hidden"])
    assert exc.value.code == 1
    assert "multiple projects" in capsys.readouterr().err


def test_get_jsonl_and_color_modes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_history(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        _run_get(
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
        _run_get(["deploy.status", "--color", "always"])
    assert exc.value.code == 0
    assert "\x1b[" in capsys.readouterr().out


def test_get_raw_non_string_is_canonical_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_history(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        _run_get(
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
        _run_get(["--format", "json", "--color", "never"])

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
        _run_get(["<build>", "--format", "json"])

    assert exc.value.code == 0
    assert json.loads(capsys.readouterr().out) == {
        "notes": "line one\nline two",
        "status": "new",
    }

    with pytest.raises(SystemExit) as exc:
        _run_get(["<build>", "--hidden", "--format", "json"])
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
        _run_get(["<build>", "--project", "alpha", "--format", "json"])
    assert exc.value.code == 0
    assert json.loads(capsys.readouterr().out) == {"where": "alpha"}

    with pytest.raises(SystemExit) as exc:
        _run_get(
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
        _run_get(["<missing>", "--project", "alpha"])
    assert exc.value.code == 1
    assert "unknown agent: missing (project alpha)" in capsys.readouterr().err

    with pytest.raises(SystemExit) as exc:
        _run_get(["<missing>", "--project", "alpha", "--project", "beta"])
    assert exc.value.code == 1
    assert "unknown agent: missing (projects alpha, beta)" in capsys.readouterr().err


def test_get_preserves_dotted_hyphenated_and_digit_snapshot_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_history(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        _run_get(["<research.foo>", "--format", "json"])
    assert exc.value.code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "member"

    with pytest.raises(SystemExit) as exc:
        _run_get(["<research.foo-bar>", "--format", "json"])
    assert exc.value.code == 0
    assert json.loads(capsys.readouterr().out) == {"status": "hyphen"}

    with pytest.raises(SystemExit) as exc:
        _run_get(["<2review>", "--format", "json"])
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
        _run_get(["<empty>", "--color", "never"])

    assert exc.value.code == 0
    assert capsys.readouterr().out == "No output variables set.\n"


def test_get_current_requires_artifacts_dir(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)

    with pytest.raises(SystemExit) as exc:
        _run_get([])

    assert exc.value.code == 1
    assert "SASE_ARTIFACTS_DIR or a quoted <agent_name>" in capsys.readouterr().err


def test_get_snapshot_color_never_has_no_ansi(
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
        _run_get(["--color", "never"])

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
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"output_variables": {"status": "ok"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))

    with pytest.raises(SystemExit) as exc:
        _run_get(["--format", fmt])
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
        _run_get(["<build>", "--format", fmt])
    assert exc.value.code == 2
    assert "build.*" in capsys.readouterr().err


def test_get_snapshot_rejects_explicit_selector_limit(
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
        _run_get(["--limit", "5"])
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
        _run_get(["<build>", "--limit", "0"])
    assert exc.value.code == 2
    assert "build.*" in capsys.readouterr().err


def test_get_wrapped_snapshot_is_not_selector_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_history(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        _run_get(["<build>", "--project", "gh_acme__widgets", "--format", "json"])
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
        _run_get(
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
