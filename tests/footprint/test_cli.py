"""Tests for the CLI Footprint recorder and its single entry seam."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

from sase.footprint._actor import classify_actor


def test_actor_matches_agent_identity_markers(
    tmp_path: Path,
) -> None:
    from sase.agent.identity import agent_marker_present

    cases: list[dict[str, str]] = [
        {},
        {"SASE_AGENT": "agent", "SASE_JOB_ROUTINE": "nightly"},
        {"SASE_AGENT_NAME": "agent"},
        {"SASE_MONITOR_ID": "monitor"},
        {"SASE_GATE_COMMAND": "1"},
        {"SASE_AGENT": "  "},
        {"SASE_ARTIFACTS_DIR": str(tmp_path)},
    ]
    (tmp_path / "agent_meta.json").write_text('{"name":"agent"}', encoding="utf-8")
    for env in cases:
        actor, _ = classify_actor(env, stdin=_Stream(False), stderr=_Stream(False))
        if "SASE_GATE_COMMAND" not in env:
            assert (actor == "agent") is agent_marker_present(env)
    assert (
        classify_actor(cases[4], stdin=_Stream(False), stderr=_Stream(False))[0]
        == "agent"
    )


def test_actor_precedence_and_client_via() -> None:
    assert classify_actor(
        {"SASE_JOB_RUN_ID": "run", "SASE_CLIENT": "nvim"},
        stdin=_Stream(True),
        stderr=_Stream(False),
    ) == ("automation", "auto")
    assert classify_actor(
        {"SASE_CLIENT": "nvim"}, stdin=_Stream(False), stderr=_Stream(False)
    ) == ("human", "editor")
    assert classify_actor(
        {"SASE_CLIENT": "telegram"}, stdin=_Stream(False), stderr=_Stream(False)
    ) == ("human", "chat")
    assert classify_actor({}, stdin=_Stream(True), stderr=_Stream(False)) == (
        "human",
        "cli",
    )
    assert classify_actor({}, stdin=_Stream(False), stderr=_Stream(False)) == (
        "unknown",
        "cli",
    )


def test_cancellation_outcomes_are_classified_without_details() -> None:
    from sase.footprint._cli import CliHit

    hit = CliHit("local", 0, "2026-10-27", "unknown", "cli")
    assert hit._outcome(KeyboardInterrupt()) == "cancelled"
    assert hit._outcome(SystemExit(130)) == "cancelled"


def test_cli_processes_record_commands_and_safe_option_destinations(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    secret = "private-project-name-should-not-be-recorded"
    cases = (
        ("version",),
        ("footprint", "mode", "--help"),
        ("footprint", "mode", "impossible"),
        ("footprint", "catalog", "--area", secret, "--format", "json"),
        ("completion", "candidates", "bead"),
    )
    for argv in cases:
        result = _run_sase(argv, home)
        if argv == ("footprint", "mode", "impossible"):
            assert result.returncode == 2

    fast_bead = _run_script(
        """
import sys
from sase.main import bead_fast_path
bead_fast_path.try_handle_bead_fast_path = lambda argv: 0
sys.argv = ['sase', 'bead', 'list', '--status', 'open']
from sase.main.entry import main
main()
""",
        home,
    )
    assert fast_bead.returncode == 0

    run_special = _run_script(
        f"""
import sys
from sase.main import query_handler
query_handler.handle_run_special_cases = lambda args: sys.exit(0)
sys.argv = ['sase', 'run', {secret!r}]
from sase.main.entry import main
main()
""",
        home,
    )
    assert run_special.returncode == 0

    plugins = _run_script(
        """
import sys
from sase.plugin_commands import dispatch
dispatch.try_handle_plugin_command = lambda argv: 0
from sase.main.entry import main
for word in ('listen', 'private-third-party-command'):
    sys.argv = ['sase', word]
    try:
        main()
    except SystemExit as exc:
        assert exc.code == 0
""",
        home,
    )
    assert plugins.returncode == 0, plugins.stderr

    records = _records(home)
    pairs = {(row["f"], row["o"]) for row in records}
    assert ("cli:version", "ok") in pairs
    assert ("cli:footprint.mode", "help") in pairs
    assert ("cli:footprint.mode", "usage_error") in pairs
    assert ("cli:footprint.catalog", "ok") in pairs
    assert ("cli:completion.candidates", "ok") in pairs
    assert ("cli:bead.list", "ok") in pairs
    assert ("cli:run", "ok") in pairs
    assert ("plugin:listen", "ok") in pairs
    assert ("plugin:~third_party", "ok") in pairs
    catalog = next(row for row in records if row["f"] == "cli:footprint.catalog")
    assert catalog["opt"] == ["area", "format"]
    contents = "\n".join(
        path.read_text(encoding="ascii") for path in spool_dir_for(home).glob("*.jsonl")
    )
    assert secret not in contents
    assert all(len(line.encode("ascii")) <= 512 for line in _raw_lines(home))


def test_recording_is_excluded_under_pytest_by_default(tmp_path: Path) -> None:
    env = _base_env(tmp_path / "home")
    env.pop("SASE_FOOTPRINT", None)
    env["PYTEST_VERSION"] = "current"
    result = subprocess.run(
        [sys.executable, "-m", "sase", "version"],
        cwd=_repo_root(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert not list(spool_dir_for(tmp_path / "home").glob("*.jsonl"))


def test_recorder_import_closure_is_limited_to_footprint_modules(
    tmp_path: Path,
) -> None:
    env = _base_env(tmp_path / "home")
    env.pop("PYTEST_CURRENT_TEST", None)
    env.pop("PYTEST_VERSION", None)
    env["SASE_FOOTPRINT"] = "local"
    script = """
import sys
import sase.main.entry as entry
before = {name for name in sys.modules if name.startswith('sase.')}
entry._main = lambda hit: None
entry.main()
after = {name for name in sys.modules if name.startswith('sase.')}
print('\\n'.join(sorted(after - before)))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=_repo_root(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    loaded = set(result.stdout.splitlines())
    allowed = {
        "sase.footprint",
        "sase.footprint._actor",
        "sase.footprint._cli",
        "sase.footprint._mode",
        "sase.footprint._spool",
        "sase.footprint.ids",
        "sase.footprint.paths",
    }
    assert loaded <= allowed
    assert allowed <= loaded


class _Stream:
    def __init__(self, tty: bool):
        self.tty = tty

    def isatty(self) -> bool:
        return self.tty


def _run_sase(argv: tuple[str, ...], home: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "sase", *argv],
        cwd=_repo_root(),
        env=_base_env(home),
        capture_output=True,
        text=True,
        check=False,
    )


def _run_script(script: str, home: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=_repo_root(),
        env=_base_env(home),
        capture_output=True,
        text=True,
        check=False,
    )


def _base_env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("SASE_SDD_"):
            env.pop(key, None)
    env["SASE_HOME"] = str(home)
    env["SASE_FOOTPRINT"] = "test"
    return env


def _records(home: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in _raw_lines(home)]


def _raw_lines(home: Path) -> list[str]:
    paths = list(spool_dir_for(home).glob("*.jsonl"))
    return [
        line for path in paths for line in path.read_text(encoding="ascii").splitlines()
    ]


def spool_dir_for(home: Path) -> Path:
    return home / "footprint" / "spool"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]
