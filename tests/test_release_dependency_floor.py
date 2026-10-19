"""Unit tests for tools/check_release_dependency_floor (fixtures, no network)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone, UTC
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "check_release_dependency_floor"


def _load_tool() -> ModuleType:
    module_name = "check_release_dependency_floor_tool"
    loader = SourceFileLoader(module_name, str(TOOL_PATH))
    spec = importlib.util.spec_from_file_location(module_name, TOOL_PATH, loader=loader)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


TOOL = _load_tool()


def _write_pyproject(path: Path, dependencies: list[str]) -> Path:
    quoted = ",\n    ".join(json.dumps(item) for item in dependencies)
    path.write_text(
        f'[project]\nname = "sase-plugin"\ndependencies = [\n    {quoted}\n]\n',
        encoding="utf-8",
    )
    return path


def _releases(*rows: tuple[str, bool]) -> dict[str, object]:
    payload: dict[str, list[dict[str, object]]] = {}
    for version, yanked in rows:
        payload[version] = [{"yanked": yanked, "filename": f"pkg-{version}.whl"}]
    return {"releases": payload}


def _fetch_map(mapping: dict[str, object]) -> object:
    def fetch(name: str) -> object:
        if name not in mapping:
            raise TOOL.PypiUnreachable(name, "not in fixture")
        value = mapping[name]
        if isinstance(value, TOOL.PypiUnreachable):
            raise value
        return value

    return fetch


def _compile_ok(_requirements: object) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")


def _compile_conflict(_requirements: object) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[],
        returncode=1,
        stdout="",
        stderr="Could not find a version that satisfies the requirement",
    )


def test_tool_script_is_executable() -> None:
    assert TOOL_PATH.exists()
    assert TOOL_PATH.stat().st_mode & 0o111


def test_unpublished_floor_is_red_with_named_reason(tmp_path: Path) -> None:
    pyproject = _write_pyproject(tmp_path / "pyproject.toml", ["sase>=0.19.0"])
    outcome = TOOL.check_floor(
        pyproject=pyproject,
        head_ref="release-please--branches--master",
        fetch_fn=_fetch_map({"sase": _releases(("0.18.0", False))}),
        run_fn=_compile_ok,
    )

    assert outcome.exit_code == 1
    assert [finding.render() for finding in outcome.findings] == [
        "DEPENDENCY_UNPUBLISHED sase>=0.19.0: newest published is 0.18.0"
    ]


def test_satisfiable_floor_is_green(tmp_path: Path) -> None:
    pyproject = _write_pyproject(tmp_path / "pyproject.toml", ["sase>=0.18.0"])
    outcome = TOOL.check_floor(
        pyproject=pyproject,
        head_ref="release-please--branches--master",
        fetch_fn=_fetch_map({"sase": _releases(("0.18.0", False), ("0.17.1", False))}),
        run_fn=_compile_ok,
    )

    assert outcome.exit_code == 0
    assert outcome.findings == ()
    assert outcome.notice is None


def test_only_prerelease_matches_are_red(tmp_path: Path) -> None:
    pyproject = _write_pyproject(tmp_path / "pyproject.toml", ["sase>=0.19.0"])
    outcome = TOOL.check_floor(
        pyproject=pyproject,
        head_ref="release-please--branches--master",
        fetch_fn=_fetch_map(
            {"sase": _releases(("0.19.0a1", False), ("0.18.0", False))}
        ),
        run_fn=_compile_ok,
    )

    assert outcome.exit_code == 1
    assert outcome.findings[0].kind == "DEPENDENCY_UNPUBLISHED"
    assert "newest published is 0.18.0" in outcome.findings[0].message


def test_only_yanked_matches_are_red(tmp_path: Path) -> None:
    pyproject = _write_pyproject(tmp_path / "pyproject.toml", ["sase>=0.19.0"])
    outcome = TOOL.check_floor(
        pyproject=pyproject,
        head_ref="release-please--branches--master",
        fetch_fn=_fetch_map({"sase": _releases(("0.19.0", True), ("0.18.0", False))}),
        run_fn=_compile_ok,
    )

    assert outcome.exit_code == 1
    assert "newest published is 0.18.0" in outcome.findings[0].message


def test_joint_conflict_is_red(tmp_path: Path) -> None:
    pyproject = _write_pyproject(
        tmp_path / "pyproject.toml",
        ["sase>=0.18.0", "requests>=99"],
    )
    outcome = TOOL.check_floor(
        pyproject=pyproject,
        head_ref="release-please--branches--master",
        fetch_fn=_fetch_map({"sase": _releases(("0.18.0", False))}),
        run_fn=_compile_conflict,
    )

    assert outcome.exit_code == 1
    assert outcome.findings[0].kind == "JOINT_RESOLVE_FAILED"
    assert "Could not find a version" in outcome.findings[0].message


def test_pypi_error_is_red_and_skips_joint(tmp_path: Path) -> None:
    pyproject = _write_pyproject(tmp_path / "pyproject.toml", ["sase>=0.18.0"])
    calls: list[Sequence[str]] = []

    def run_fn(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return _compile_ok(cmd)

    outcome = TOOL.check_floor(
        pyproject=pyproject,
        head_ref="release-please--branches--master",
        fetch_fn=_fetch_map(
            {"sase": TOOL.PypiUnreachable("sase", "HTTP 503 from PyPI")}
        ),
        run_fn=run_fn,
    )

    assert outcome.exit_code == 1
    assert [finding.render() for finding in outcome.findings] == [
        "PYPI_UNREACHABLE sase: HTTP 503 from PyPI"
    ]
    assert calls == []


def test_optional_and_dev_dependencies_are_ignored(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "[project]\n"
        'name = "sase-plugin"\n'
        "dependencies = [\n"
        '    "sase>=0.18.0",\n'
        "]\n"
        "[project.optional-dependencies]\n"
        "dev = [\n"
        '    "sase>=99",\n'
        "]\n"
        "[dependency-groups]\n"
        'dev = ["sase>=99"]\n',
        encoding="utf-8",
    )
    outcome = TOOL.check_floor(
        pyproject=pyproject,
        head_ref="release-please--branches--master",
        fetch_fn=_fetch_map({"sase": _releases(("0.18.0", False))}),
        run_fn=_compile_ok,
    )

    assert outcome.exit_code == 0
    assert outcome.findings == ()


def test_non_family_deps_are_ignored_by_the_sibling_rule(tmp_path: Path) -> None:
    pyproject = _write_pyproject(
        tmp_path / "pyproject.toml",
        ["sase>=0.18.0", "PyYAML>=6.0", "python-telegram-bot>=21.0"],
    )
    fetched: list[str] = []

    def fetch(name: str) -> object:
        fetched.append(name)
        return _releases(("0.18.0", False))

    outcome = TOOL.check_floor(
        pyproject=pyproject,
        head_ref="release-please--branches--master",
        fetch_fn=fetch,
        run_fn=_compile_ok,
    )

    assert outcome.exit_code == 0
    assert fetched == ["sase"]


def test_core_rs_is_a_family_sibling(tmp_path: Path) -> None:
    pyproject = _write_pyproject(
        tmp_path / "pyproject.toml",
        ["sase>=0.18.0", "sase-core-rs>=0.35.0"],
    )
    fetched: list[str] = []

    def fetch(name: str) -> object:
        fetched.append(name)
        return _releases(("0.42.1", False), ("0.18.0", False))

    outcome = TOOL.check_floor(
        pyproject=pyproject,
        head_ref="release-please--branches--master",
        fetch_fn=fetch,
        run_fn=_compile_ok,
    )

    assert outcome.exit_code == 0
    assert fetched == ["sase", "sase-core-rs"]


def test_non_release_head_ref_passes_with_a_notice(tmp_path: Path) -> None:
    pyproject = _write_pyproject(tmp_path / "pyproject.toml", ["sase>=99"])
    outcome = TOOL.check_floor(
        pyproject=pyproject,
        head_ref="feature/bump-floor",
        fetch_fn=_fetch_map({}),
        run_fn=_compile_conflict,
    )

    assert outcome.exit_code == 0
    assert outcome.findings == ()
    assert outcome.notice is not None
    assert "feature/bump-floor" in outcome.notice
    assert "not a release-please branch" in outcome.notice


def test_probe_extra_requirement_enforces_on_a_non_release_ref(
    tmp_path: Path,
) -> None:
    pyproject = _write_pyproject(tmp_path / "pyproject.toml", ["sase>=0.18.0"])
    outcome = TOOL.check_floor(
        pyproject=pyproject,
        head_ref="master",
        extra_requirement="sase>=99",
        fetch_fn=_fetch_map({"sase": _releases(("0.18.0", False))}),
        run_fn=_compile_ok,
    )

    assert outcome.exit_code == 1
    assert any(
        "DEPENDENCY_UNPUBLISHED sase>=99" in finding.render()
        for finding in outcome.findings
    )


def test_malformed_pypi_json_fails_closed(tmp_path: Path) -> None:
    pyproject = _write_pyproject(tmp_path / "pyproject.toml", ["sase>=0.18.0"])
    outcome = TOOL.check_floor(
        pyproject=pyproject,
        head_ref="release-please--branches--master",
        fetch_fn=_fetch_map({"sase": {"info": {"version": "0.18.0"}}}),
        run_fn=_compile_ok,
    )

    assert outcome.exit_code == 1
    assert outcome.findings[0].kind == "PYPI_UNREACHABLE"
    assert "malformed JSON" in outcome.findings[0].message


def test_main_prints_notice_and_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pyproject = _write_pyproject(tmp_path / "pyproject.toml", ["sase>=99"])
    exit_code = TOOL.main(["--pyproject", str(pyproject), "--head-ref", "feature/x"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "NOTICE:" in captured.out
    assert captured.err == ""


def test_main_prints_unpublished_reason_on_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pyproject = _write_pyproject(tmp_path / "pyproject.toml", ["sase>=0.19.0"])
    # main() hits the network unless we go through check_floor; drive the
    # printer via _print_outcome so this test stays fixture-only.
    outcome = TOOL.CheckOutcome(
        exit_code=1,
        notice=None,
        findings=(
            TOOL.unpublished_finding(
                TOOL.Requirement("sase>=0.19.0"),
                "0.18.0",
            ),
        ),
    )
    exit_code = TOOL._print_outcome(outcome)
    captured = capsys.readouterr()

    assert exit_code == 1
    assert pyproject.name == "pyproject.toml"
    assert (
        captured.err
        == "DEPENDENCY_UNPUBLISHED sase>=0.19.0: newest published is 0.18.0\n"
    )


def test_should_rerun_hourly_then_backs_off() -> None:
    now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    created = now - timedelta(hours=2)
    run = TOOL.WorkflowRun(
        database_id=1,
        head_sha="abc",
        conclusion="failure",
        status="completed",
        attempt=3,
        created_at=created,
        updated_at=now - timedelta(hours=1),
    )
    rerun, reason = TOOL.should_rerun_failed(run, now=now)
    assert rerun is True
    assert reason == "hourly window"

    late = TOOL.WorkflowRun(
        database_id=1,
        head_sha="abc",
        conclusion="failure",
        status="completed",
        attempt=25,
        created_at=now - timedelta(hours=30),
        updated_at=now - timedelta(hours=1),
    )
    rerun, reason = TOOL.should_rerun_failed(late, now=now)
    assert rerun is False
    assert "backing off" in reason

    ready = TOOL.WorkflowRun(
        database_id=1,
        head_sha="abc",
        conclusion="failure",
        status="completed",
        attempt=25,
        created_at=now - timedelta(hours=30),
        updated_at=now - timedelta(hours=4),
    )
    rerun, reason = TOOL.should_rerun_failed(ready, now=now)
    assert rerun is True
    assert reason == "post-day backoff"


def test_should_rerun_stops_at_github_attempt_cap() -> None:
    now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    run = TOOL.WorkflowRun(
        database_id=1,
        head_sha="abc",
        conclusion="failure",
        status="completed",
        attempt=50,
        created_at=now - timedelta(hours=1),
        updated_at=now - timedelta(hours=1),
    )
    rerun, reason = TOOL.should_rerun_failed(run, now=now)
    assert rerun is False
    assert "50 re-runs" in reason


def test_rerun_skips_non_schedule_events() -> None:
    exit_code, lines = TOOL.rerun_failed_floor_checks(
        repo="sase-org/sase-github",
        event_name="pull_request",
        run_fn=lambda _cmd: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="[]", stderr=""
        ),
    )
    assert exit_code == 0
    assert lines == ["NOTICE: event 'pull_request' does not rerun failed floor checks."]


def test_rerun_calls_gh_run_rerun_failed_on_a_failed_pr_run() -> None:
    now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    created = (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    commands: list[list[str]] = []

    def run_fn(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
        commands.append(list(cmd))
        if cmd[:3] == ["gh", "pr", "list"]:
            return subprocess.CompletedProcess(
                args=list(cmd),
                returncode=0,
                stdout=json.dumps(
                    [
                        {
                            "number": 12,
                            "headRefName": "release-please--branches--master",
                            "headRefOid": "deadbeef" * 5,
                        }
                    ]
                ),
                stderr="",
            )
        if cmd[:3] == ["gh", "run", "list"]:
            return subprocess.CompletedProcess(
                args=list(cmd),
                returncode=0,
                stdout=json.dumps(
                    [
                        {
                            "databaseId": 99,
                            "headSha": "deadbeef" * 5,
                            "conclusion": "failure",
                            "status": "completed",
                            "attempt": 2,
                            "createdAt": created,
                            "updatedAt": created,
                        }
                    ]
                ),
                stderr="",
            )
        if cmd[:3] == ["gh", "run", "rerun"]:
            return subprocess.CompletedProcess(
                args=list(cmd), returncode=0, stdout="ok", stderr=""
            )
        raise AssertionError(cmd)

    exit_code, lines = TOOL.rerun_failed_floor_checks(
        repo="sase-org/sase-github",
        event_name="schedule",
        now=now,
        run_fn=run_fn,
    )

    assert exit_code == 0
    assert any("reran 99" in line for line in lines)
    assert [
        "gh",
        "run",
        "rerun",
        "99",
        "--repo",
        "sase-org/sase-github",
        "--failed",
    ] in commands


def test_is_family_package_matches_sase_star_only() -> None:
    assert TOOL.is_family_package("sase")
    assert TOOL.is_family_package("Sase_GitHub")
    assert TOOL.is_family_package("sase-core-rs")
    assert not TOOL.is_family_package("requests")
    assert not TOOL.is_family_package("sasey")
