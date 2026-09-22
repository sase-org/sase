from __future__ import annotations

import os
from pathlib import Path
import stat
import sys
import textwrap

import pytest
import yaml

from sase.config.core import clear_config_cache
from sase.core.tool_run import tool_run_list, tool_run_show
from sase.tool.executor import ToolRunCliRequest, execute_tool_run


def _home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SASE_HOME", str(home))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    monkeypatch.delenv("SASE_MONITOR_ID", raising=False)
    monkeypatch.delenv("SASE_MONITOR_ARTIFACTS_DIR", raising=False)
    monkeypatch.delenv("SASE_PROC_ID", raising=False)
    monkeypatch.delenv("SASE_TOOL_RUN_ID", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    clear_config_cache()
    return home


def _run(
    *argv: str, quiet: bool = False, verbose: bool = False, tail: int = 200
) -> int:
    return execute_tool_run(
        ToolRunCliRequest(
            quiet=quiet,
            verbose=verbose,
            tail_lines=tail,
            words=argv,
        )
    )


def test_adhoc_two_stream_exit_and_show(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _home(monkeypatch, tmp_path)
    code = _run("--", "sh", "-c", "printf out; printf err >&2; exit 3")
    captured = capsys.readouterr()
    assert code == 3
    assert captured.out == "out"
    assert "err" in captured.err
    assert "sase tool run " in captured.err
    listed = tool_run_list({"schema_version": 1, "limit": 10})
    run = listed["runs"][0]
    assert run["state"] == "failed"
    assert run["exit_code"] == 3
    shown = tool_run_show(run["run_id"])
    assert shown["run"]["logs"]["stdout_path"]
    stdout_log = Path(shown["run"]["logs"]["stdout_path"])
    assert stdout_log.read_bytes() == b"out"


def test_literal_argv_preserves_spaces_and_dashes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _home(monkeypatch, tmp_path)
    code = _run(
        "--",
        sys.executable,
        "-c",
        "import sys; sys.stdout.write(repr(sys.argv[1:]))",
        "a b",
        "--",
        "-n",
    )
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == "['a b', '--', '-n']"


def test_nonexistent_executable_exits_127(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _home(monkeypatch, tmp_path)
    code = _run("--", str(tmp_path / "missing-cmd"))
    captured = capsys.readouterr()
    assert code == 127
    assert "executable not found" in captured.err
    assert captured.out == ""
    header_lines = [
        line for line in captured.err.splitlines() if "sase tool run " in line
    ]
    assert len(header_lines) == 1
    run_id = header_lines[0].split("sase tool run ")[1].strip().split()[0]
    run = tool_run_list({"schema_version": 1, "limit": 1})["runs"][0]
    assert run["state"] == "failed"
    assert run["exit_code"] == 127
    assert run["run_id"] == run_id
    shown = tool_run_show(run_id)
    assert shown["run"]["run_id"] == run_id


def test_not_executable_exits_126(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _home(monkeypatch, tmp_path)
    script = tmp_path / "not-exec"
    script.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    script.chmod(stat.S_IRUSR)
    code = _run("--", str(script))
    captured = capsys.readouterr()
    assert code == 126
    assert "not executable" in captured.err
    assert captured.out == ""
    header_lines = [
        line for line in captured.err.splitlines() if "sase tool run " in line
    ]
    assert len(header_lines) == 1
    run_id = header_lines[0].split("sase tool run ")[1].strip().split()[0]
    run = tool_run_list({"schema_version": 1, "limit": 1})["runs"][0]
    assert run["state"] == "failed"
    assert run["exit_code"] == 126
    assert run["run_id"] == run_id
    shown = tool_run_show(run_id)
    assert shown["run"]["run_id"] == run_id


def test_fail_open_unwritable_store_executes_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = _home(monkeypatch, tmp_path)
    (home / "tools").write_text("not-a-directory", encoding="utf-8")
    code = _run("--", "printf", "hi")
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == "hi"
    assert "run not recorded" in captured.err
    listed = tool_run_list({"schema_version": 1, "limit": 10})
    assert not listed.get("runs")


def test_running_row_visible_before_child(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    home = _home(monkeypatch, tmp_path)
    marker = tmp_path / "marker"
    script = tmp_path / "child.py"
    script.write_text(
        textwrap.dedent(
            """
            import os
            import sqlite3
            from pathlib import Path
            run_id = os.environ["SASE_TOOL_RUN_ID"]
            store = Path(os.environ["SASE_HOME"]) / "tools" / "runs.sqlite"
            con = sqlite3.connect(store)
            row = con.execute(
                "select state from runs where run_id = ?", (run_id,)
            ).fetchone()
            Path(os.environ["MARKER"]).write_text(row[0] if row else "missing")
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MARKER", str(marker))
    code = _run("--", sys.executable, str(script))
    assert code == 0
    assert marker.read_text(encoding="utf-8") == "running"
    assert (home / "tools" / "runs.sqlite").is_file()


def test_nested_run_has_parent_and_no_duplicate_logs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _home(monkeypatch, tmp_path)
    inner = tmp_path / "inner.py"
    inner.write_text(
        textwrap.dedent(
            """
            from sase.tool.executor import ToolRunCliRequest, execute_tool_run
            raise SystemExit(execute_tool_run(ToolRunCliRequest(
                quiet=False, verbose=False, tail_lines=200,
                words=("--", "printf", "inner"),
            )))
            """
        ),
        encoding="utf-8",
    )
    code = _run("--", sys.executable, str(inner))
    assert code == 0
    listed = tool_run_list({"schema_version": 1, "limit": 10})
    runs = listed["runs"]
    assert len(runs) == 2
    by_parent = {run.get("parent_run_id"): run for run in runs}
    child = next(run for run in runs if run.get("parent_run_id"))
    parent = next(run for run in runs if run.get("parent_run_id") is None)
    assert child["parent_run_id"] == parent["run_id"]
    assert child["logs"].get("stdout_path") in (None, "")
    assert parent["logs"].get("stdout_path")
    assert by_parent  # silence unused if layout changes


def test_quiet_with_enclosing_owner_is_usage_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _home(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_MONITOR_ID", "mon-1")
    code = _run("--", "printf", "hi", quiet=True)
    captured = capsys.readouterr()
    assert code == 2
    assert "quiet" in captured.err
    listed = tool_run_list({"schema_version": 1, "limit": 10})
    assert not listed.get("runs")


def test_monitor_owner_skips_stdout_logs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _home(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_MONITOR_ID", "mon-owner")
    code = _run("--", "sh", "-c", "printf out; printf err >&2")
    captured = capsys.readouterr()
    assert code == 0
    # Owner mode merges both child streams into one pipe: everything passes
    # through once, on stdout, in write order.
    assert captured.out == "outerr"
    assert "err" not in captured.err
    run = tool_run_list({"schema_version": 1, "limit": 1})["runs"][0]
    assert run["owner_kind"] == "monitor"
    assert run["owner_id"] == "mon-owner"
    assert run["logs"].get("stdout_path") in (None, "")
    assert run["logs"].get("events_path")


def test_agent_default_is_compact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _home(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_AGENT_NAME", "fixture.agent")
    code = _run(
        "--",
        "sh",
        "-c",
        "printf '%s\\n' line1 line2 line3; exit 1",
        tail=2,
    )
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "line2" in captured.err
    assert "line3" in captured.err
    assert "sase tool show " in captured.err
    assert " -l" in captured.err


def test_binary_bytes_are_not_rewritten(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _home(monkeypatch, tmp_path)
    code = _run(
        "--",
        sys.executable,
        "-c",
        "import sys; sys.stdout.buffer.write(bytes((0xFF, 0xFE)))",
    )
    assert code == 0
    run = tool_run_list({"schema_version": 1, "limit": 1})["runs"][0]
    stdout_log = Path(run["logs"]["stdout_path"])
    assert stdout_log.read_bytes() == b"\xff\xfe"


def test_named_tool_runs_at_project_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _home(monkeypatch, tmp_path)
    (tmp_path / "sase").mkdir()
    (tmp_path / "sase" / "sase.yml").write_text(
        yaml.dump({"tools": {"pwdtool": {"argv": ["pwd"], "args": "deny"}}}),
        encoding="utf-8",
    )
    nested = tmp_path / "nested"
    nested.mkdir()
    monkeypatch.chdir(nested)
    clear_config_cache()
    code = _run("pwdtool")
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.strip() == str(tmp_path)


def test_settled_monitor_id_is_stale_and_neither_owns_nor_records_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.tool.ownership import resolve_ownership

    _home(monkeypatch, tmp_path)
    artifacts = tmp_path / "monitor-artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_MONITOR_ID", "epic-launch-monitor")
    monkeypatch.setenv("SASE_MONITOR_ARTIFACTS_DIR", str(artifacts))

    running = resolve_ownership(quiet=False)
    assert (running.owner_kind, running.owner_id) == ("monitor", "epic-launch-monitor")
    assert running.owns_output is False

    (artifacts / "done.json").write_text("{}", encoding="utf-8")
    settled = resolve_ownership(quiet=True)
    assert (settled.owner_kind, settled.owner_id) == (None, None)
    assert settled.owns_output is True

    monkeypatch.setenv("SASE_AGENT_NAME", "phase-agent")
    assert _run("--", "sh", "-c", "printf out; exit 4") == 4
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "failed/4" in captured.err
    run = tool_run_list({"schema_version": 1, "limit": 1})["runs"][0]
    assert run.get("owner_kind") is None
    assert Path(run["logs"]["stdout_path"]).read_bytes() == b"out"


def test_settled_proc_id_is_stale_but_unknown_or_running_procs_still_own(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from types import SimpleNamespace

    from sase.tool import ownership

    _home(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_PROC_ID", "proc-1")
    statuses: dict[str, str | None] = {"proc-1": "success"}
    monkeypatch.setattr(
        "sase.procs.store.get_proc",
        lambda proc_id: (
            SimpleNamespace(status=statuses[proc_id]) if statuses.get(proc_id) else None
        ),
    )
    assert ownership.resolve_ownership(quiet=False).owner_kind is None

    statuses["proc-1"] = "running"
    assert ownership.resolve_ownership(quiet=False).owner_kind == "proc"

    statuses["proc-1"] = None  # not in the store: unknown liveness is not proof
    assert ownership.resolve_ownership(quiet=False).owner_kind == "proc"

    def boom(proc_id: str) -> None:
        raise RuntimeError("store unreadable")

    monkeypatch.setattr("sase.procs.store.get_proc", boom)
    assert ownership.resolve_ownership(quiet=False).owner_kind == "proc"
