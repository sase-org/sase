"""Known-gated continuation for agent-attributed runs (``sase-18j.7``)."""

from __future__ import annotations

import json
import shlex
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from sase.config.core import clear_config_cache
from sase.core.tool_run import tool_run_list, tool_run_triage_show
from sase.tool.adopt import execute_adopted_run
from sase.tool.argv import ResolvedToolArgv
from sase.tool.executor import ToolRunCliRequest, execute_tool_run
from sase.tool.triage_stage import _stage_decision


ROOT = Path(__file__).resolve().parents[2]
RUN_SILENT = ROOT / "tools" / "run_silent"
HELPER = ROOT / "tools" / "_run_silent_record.py"
MYPY_OUTPUT = "sh -c 'printf \"src/foo.py:1: error: boom  [attr-defined]\\n\"; exit 1'"


def _home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SASE_HOME", str(home))
    for name in (
        "SASE_AGENT_NAME",
        "SASE_MONITOR_ID",
        "SASE_PROC_ID",
        "SASE_TOOL_CONTINUE",
        "SASE_TOOL_PYTHON",
        "SASE_TOOL_RUN_ID",
        "SASE_TOOL_RUN_EVENTS",
        "SASE_TOOL_RUN_AGENT",
        "SASE_TOOL_TRIAGE_TIMEOUT_S",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    clear_config_cache()
    return home


def _project(tmp_path: Path, script: str) -> Path:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    sase_dir = root / "sase"
    sase_dir.mkdir()
    catalog = {
        "tools": {
            "check": {
                "argv": ["bash", "-lc", script],
                "description": "known-gated fixture",
                "stages": "run_silent",
                "inputs": [],
                "env": [],
                "args": "deny",
                "fingerprint": {"repos": [], "toolchain": {}},
            }
        }
    }
    (sase_dir / "sase.yml").write_text(yaml.safe_dump(catalog), encoding="utf-8")
    return root


def _commit(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "user.name=Fixture",
            "commit",
            "-m",
            "fixture",
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )


def _stage(description: str, shell: str) -> str:
    return f"{shlex.quote(str(RUN_SILENT))} {shlex.quote(description)} {shell}"


def _finish() -> str:
    return f"{shlex.quote(str(RUN_SILENT))} --finish"


def _run(*, keep_going: bool = False, fail_fast: bool = False) -> int:
    return execute_tool_run(
        ToolRunCliRequest(
            quiet=False,
            verbose=False,
            tail_lines=200,
            words=("check",),
            keep_going=keep_going,
            fail_fast=fail_fast,
        )
    )


def _stored_stages(run_id: str) -> list[dict[str, Any]]:
    from sase.core.tool_run import tool_run_show

    shown = tool_run_show(run_id)
    return [s for s in shown.get("stages") or () if isinstance(s, dict)]


def _events_for(run_id: str) -> list[dict[str, Any]]:
    from sase.core.tool_run import tool_run_show

    shown = tool_run_show(run_id)
    events = Path(str(shown["run"]["logs"]["events_path"]))
    return [json.loads(line) for line in events.read_text().splitlines()]


def _resolved(stages: str = "run_silent") -> ResolvedToolArgv:
    return ResolvedToolArgv(
        tool_name="check",
        argv=("bash", "-lc", "true"),
        extra_args=(),
        display_argv=("bash", "-lc", "true"),
        private_argv=None,
        definition={
            "argv": ["bash", "-lc", "true"],
            "description": "fixture",
            "stages": stages,
            "inputs": [],
            "env": [],
            "args": "deny",
            "fingerprint": {},
        },
        digest="fixture",
        cwd="/tmp",
        adhoc=False,
    )


def test_stage_decision_requires_all_known_or_flaky() -> None:
    def _item(class_name: str | None) -> dict[str, Any]:
        return {"label": None if class_name is None else {"class": class_name}}

    decision, reason, counts = _stage_decision(
        [_item("known"), _item("flaky"), _item("KNOWN".lower())]
    )
    assert (decision, reason) == ("continue", "all_known_or_flaky")
    assert counts == {"new": 0, "known": 2, "flaky": 1, "unknown": 0}

    assert _stage_decision([_item("known"), _item("new")])[0:2] == (
        "stop",
        "new_item",
    )
    assert _stage_decision([_item("known"), _item("unknown")])[0:2] == (
        "stop",
        "unknown_item",
    )
    assert _stage_decision([_item("known"), _item(None)])[0:2] == (
        "stop",
        "unknown_item",
    )
    assert _stage_decision([])[0:2] == ("stop", "no_items")
    assert _stage_decision(None)[0:2] == ("stop", "no_items")


def test_agent_default_continuation_mode_needs_agent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _home(monkeypatch, tmp_path)
    from sase.tool.executor import agent_default_continuation_mode

    assert agent_default_continuation_mode(_resolved(), "agent-1") == "known"
    assert agent_default_continuation_mode(_resolved(), "  ") == "never"
    assert agent_default_continuation_mode(_resolved(), None) == "never"
    assert agent_default_continuation_mode(_resolved(stages="none"), "agent-1") is None


def test_adopted_worker_inherits_recorded_starter_agent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _home(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_MONITOR_ID", "monitor-1")
    monkeypatch.setenv("SASE_PROC_ID", "proc-1")

    import sase.tool.adopt as adopt_module

    seen: dict[str, Any] = {}

    def _claim(request: dict[str, Any]) -> dict[str, Any]:
        return {
            "outcome": "claimed",
            "launch": {
                "argv": ["bash", "-lc", "true"],
                "cwd": str(tmp_path),
                "tool_name": "check",
                "extra_args": [],
                "display_argv": ["bash", "-lc", "true"],
                "private_argv": None,
                "definition": {
                    "argv": ["bash", "-lc", "true"],
                    "description": "fixture",
                    "stages": "run_silent",
                    "inputs": [],
                    "env": [],
                    "args": "deny",
                    "fingerprint": {},
                },
                "digest": "fixture",
                "adhoc": False,
            },
            "run": {"agent": "starter-1", "logs": {}},
        }

    def _body(ctx: Any, signals: Any) -> int:
        seen["mode"] = ctx.continuation_mode
        return 0

    monkeypatch.setattr(adopt_module, "tool_run_claim", _claim)
    monkeypatch.setattr(adopt_module, "run_recorded_body", _body)

    assert execute_adopted_run("run-1") == 0
    assert seen["mode"] == "known"


def test_agent_run_continues_past_all_known_stage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _home(monkeypatch, tmp_path)
    script = " && ".join(
        (
            _stage("lint (mypy)", MYPY_OUTPUT),
            _stage("unit", "true"),
            _finish(),
        )
    )
    root = _project(tmp_path, script)
    _commit(root)
    monkeypatch.chdir(root)

    assert _run(keep_going=True) == 1
    seed_id = tool_run_list({"schema_version": 1, "limit": 1})["runs"][0]["run_id"]
    capsys.readouterr()

    monkeypatch.setenv("SASE_AGENT_NAME", "e2e-agent")
    assert _run() == 1
    captured = capsys.readouterr()
    assert "verdict: no_new_failures" in captured.err

    # ``created_ts`` has second granularity, so two fast runs can tie for
    # newest; resolve the second run by exclusion instead of order.
    listed = tool_run_list({"schema_version": 1, "limit": 10})["runs"]
    run_id = next(r["run_id"] for r in listed if r["run_id"] != seed_id)
    records = _events_for(run_id)
    assert [s["description"] for s in _stored_stages(run_id)] == [
        "lint (mypy)",
        "unit",
    ]
    continued = [r for r in records if r.get("kind") == "continued"]
    assert len(continued) == 1
    assert continued[0]["mode"] == "known"
    assert continued[0]["reason"] == "all_known_or_flaky"
    assert type(continued[0]["elapsed_ms"]) is int
    assert records[-1]["kind"] == "recipe_finished"

    triage = tool_run_triage_show({"run_id": run_id})
    assert triage["triaged"] is True, triage["diagnostics"]
    assert triage["verdict"] == "no_new_failures"
    stage = next(s for s in triage["stages"] if s["stage_key"] == "lint (mypy)")
    decision = stage["decision"]
    assert decision["decision"] == "continue"
    assert decision["mode"] == "known"
    assert decision["reason"] == "all_known_or_flaky"
    assert type(decision["elapsed_ms"]) is int
    assert type(decision["decided_ts"]) is int
    items = [i for i in triage["items"] if i["stage_key"] == "lint (mypy)"]
    assert items and all(i["label"]["class"] == "known" for i in items)
    witnesses = items[0]["label"]["evidence"]["witness_run_ids"]
    assert seed_id in witnesses
    run_facts = triage.get("run_facts") or {}
    assert type(run_facts.get("continuation_extra_ms")) is int
    assert run_facts.get("continuation_extra_ms", -1) >= 0


def test_agent_run_stops_on_a_new_item(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _home(monkeypatch, tmp_path)
    script = " && ".join(
        (
            _stage(
                "lint (mypy)",
                "sh -c 'printf \"src/unique.py:9: error: "
                "never-seen-before  [attr-defined]\\n\"; exit 4'",
            ),
            _stage("unit", "true"),
            _finish(),
        )
    )
    root = _project(tmp_path, script)
    _commit(root)
    monkeypatch.chdir(root)

    monkeypatch.setenv("SASE_AGENT_NAME", "e2e-agent")
    assert _run() == 4
    run_id = tool_run_list({"schema_version": 1, "limit": 1})["runs"][0]["run_id"]
    records = _events_for(run_id)
    stopped = [r for r in records if r.get("kind") == "stopped"]
    assert len(stopped) == 1
    assert stopped[0]["mode"] == "known"
    assert stopped[0]["reason"] in {"new_item", "unknown_item"}
    assert not any(r.get("kind") == "continued" for r in records)

    triage = tool_run_triage_show({"run_id": run_id})
    stage = next(s for s in triage["stages"] if s["stage_key"] == "lint (mypy)")
    assert stage["decision"]["decision"] == "stop"


def test_agent_run_stops_on_generic_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _home(monkeypatch, tmp_path)
    script = " && ".join(
        (
            _stage("opaque", "sh -c 'echo plain boom with no shape; exit 3'"),
            _stage("unit", "true"),
            _finish(),
        )
    )
    root = _project(tmp_path, script)
    _commit(root)
    monkeypatch.chdir(root)

    monkeypatch.setenv("SASE_AGENT_NAME", "e2e-agent")
    assert _run() == 3
    run_id = tool_run_list({"schema_version": 1, "limit": 1})["runs"][0]["run_id"]
    records = _events_for(run_id)
    stopped = [r for r in records if r.get("kind") == "stopped"]
    assert len(stopped) == 1
    assert stopped[0]["reason"] == "unknown_item"

    triage = tool_run_triage_show({"run_id": run_id})
    items = [i for i in triage["items"] if i["stage_key"] == "opaque"]
    assert items
    assert all(i["label"]["class"] == "unknown" for i in items)


def test_human_run_defaults_to_never(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _home(monkeypatch, tmp_path)
    script = " && ".join(
        (
            _stage("one", "sh -c 'exit 7'"),
            _stage("two", "true"),
            _finish(),
        )
    )
    root = _project(tmp_path, script)
    monkeypatch.chdir(root)

    assert _run() == 7
    run_id = tool_run_list({"schema_version": 1, "limit": 1})["runs"][0]["run_id"]
    records = _events_for(run_id)
    stopped = [r for r in records if r.get("kind") == "stopped"]
    assert [r["reason"] for r in stopped] == ["mode_never"]
    assert not any(r.get("kind") == "continued" for r in records)


def _helper_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, python: str
) -> tuple[Path, Path]:
    events = tmp_path / "events.jsonl"
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": "run-1",
                "stage_id": "stage-1",
                "description": "stage",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_TOOL_RUN_EVENTS", str(events))
    monkeypatch.setenv("SASE_TOOL_RUN_ID", "run-1")
    monkeypatch.setenv("SASE_TOOL_PYTHON", python)
    monkeypatch.delenv("SASE_TOOL_TRIAGE_TIMEOUT_S", raising=False)
    return events, state


def _write_fake(tmp_path: Path, name: str, body: str) -> str:
    path = tmp_path / name
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(path)


def _decide(state: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "decide",
            "--state",
            str(state),
            "--description",
            "stage",
            "--exit-code",
            "7",
            "--mode",
            "known",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_helper_timeout_stops_the_stage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _write_fake(tmp_path, "slow-python", "sleep 30")
    events, state = _helper_env(monkeypatch, tmp_path, fake)
    monkeypatch.setenv("SASE_TOOL_TRIAGE_TIMEOUT_S", "1")

    completed = _decide(state)

    assert completed.returncode == 7
    records = [json.loads(line) for line in events.read_text().splitlines()]
    stopped = [r for r in records if r.get("kind") == "stopped"]
    assert len(stopped) == 1
    assert stopped[0]["reason"] == "helper_timeout"


def test_helper_crash_stops_the_stage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _write_fake(tmp_path, "crash-python", "echo not-json; exit 5")
    events, state = _helper_env(monkeypatch, tmp_path, fake)

    completed = _decide(state)

    assert completed.returncode == 7
    records = [json.loads(line) for line in events.read_text().splitlines()]
    stopped = [r for r in records if r.get("kind") == "stopped"]
    assert len(stopped) == 1
    assert stopped[0]["reason"] == "helper_error"


def test_helper_without_handshake_stays_fail_fast(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps({"schema_version": 1, "stage_id": "stage-1"}), encoding="utf-8"
    )
    monkeypatch.delenv("SASE_TOOL_RUN_EVENTS", raising=False)
    monkeypatch.delenv("SASE_TOOL_RUN_ID", raising=False)

    completed = _decide(state)

    assert completed.returncode == 7
