"""Hermetic E3 failure-triage cases for the ToolRun black-box harness."""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any

from _smoke_tool_runs_lib import Harness, RUN_SILENT, case, run_id_from


def _stage(description: str, command: str) -> str:
    return f'"$RS" {shlex.quote(description)} {command} || exit $?'


def _project(h: Harness, name: str, script: str) -> Path:
    return h.make_project(
        name,
        {
            "check": {
                "argv": ["bash", "check.sh"],
                "description": "E3 triage fixture check.",
                "stages": "run_silent",
                "inputs": [],
                "env": [],
                "args": "deny",
                "fingerprint": {"repos": [], "toolchain": {}},
            }
        },
        {"check.sh": f"set -u\nRS={json.dumps(str(RUN_SILENT))}\n{script}\n"},
    )


def _agent_env(h: Harness, world: dict[str, str], agent: str) -> dict[str, str]:
    return h.env(
        Path(world["SASE_HOME"]), HOME=world["HOME"], SASE_AGENT_NAME=agent
    )


def _events(h: Harness, run_id: str, env: dict[str, str]) -> list[dict[str, Any]]:
    shown = h.show(run_id, env=env)
    logs = (shown.get("run") or {}).get("logs") or {}
    path = Path(str(logs.get("events_path") or ""))
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def failure_triage(h: Harness) -> list[dict[str, Any]]:
    """Exercise E3's observable triage contract through the real CLI/store."""

    known_output = (
        "sh -c 'printf \"src/known.py:1: error: established  [attr-defined]\\n\"; "
        "exit 7'"
    )
    continuing_script = "\n".join(
        (
            _stage("lint (mypy)", known_output),
            '"$RS" "test (scoped)" sh -c \'printf "SCOPED_TEST_REACHED\\n"\'',
            '"$RS" --finish',
        )
    )
    project = _project(h, "triage-known", continuing_script)
    world = h.world("triage-known")
    seed = h.run(["tool", "run", "check"], env=world, cwd=project)
    seed_id = run_id_from(seed.stderr)
    agent = h.run(
        ["tool", "run", "check"],
        env=_agent_env(h, world, "triage-smoke-agent"),
        cwd=project,
    )
    agent_id = run_id_from(agent.stderr)
    shown = h.show(agent_id, env=world)
    triage = shown.get("triage") or {}
    stages = [stage.get("description") for stage in shown.get("stages") or ()]
    events = _events(h, agent_id, world)
    continued = [event for event in events if event.get("kind") == "continued"]
    known_ok = (
        seed.returncode == 7
        and agent.returncode == 7
        and "test (scoped)" in stages
        and triage.get("verdict") == "no_new_failures"
        and len(continued) == 1
        and continued[0].get("reason") == "all_known_or_flaky"
        and "verdict: no_new_failures" in agent.stderr
    )
    h.note(seed_id, "triage witness for all-KNOWN continuation")
    h.note(agent_id, "agent check continued through all-KNOWN stage")

    new_script = "\n".join(
        (
            _stage(
                "lint (mypy)",
                "sh -c 'printf \"src/new.py:1: error: unseen  [attr-defined]\\n\"; exit 4'",
            ),
            '"$RS" "test (scoped)" sh -c \'printf "SHOULD_NOT_REACH\\n"\'',
            '"$RS" --finish',
        )
    )
    new_project = _project(h, "triage-new", new_script)
    new_world = h.world("triage-new")
    new_run = h.run(
        ["tool", "run", "check"],
        env=_agent_env(h, new_world, "triage-smoke-agent"),
        cwd=new_project,
    )
    new_id = run_id_from(new_run.stderr)
    stopped = [
        event
        for event in _events(h, new_id, new_world)
        if event.get("kind") == "stopped"
    ]
    new_ok = (
        new_run.returncode == 4
        and "SHOULD_NOT_REACH" not in new_run.stdout
        and len(stopped) == 1
        and stopped[0].get("reason") in {"new_item", "unknown_item"}
    )
    h.note(new_id, "agent check stopped on a NEW/UNKNOWN triage item")

    unfinished_project = _project(h, "triage-safety", _stage("lint (mypy)", known_output))
    unfinished_world = h.world("triage-safety")
    witness = h.run(
        ["tool", "run", "check"], env=unfinished_world, cwd=unfinished_project
    )
    safety = h.run(
        ["tool", "run", "check"],
        env=_agent_env(h, unfinished_world, "triage-smoke-agent"),
        cwd=unfinished_project,
    )
    safety_id = run_id_from(safety.stderr)
    safety_run = h.show(safety_id, env=unfinished_world).get("run") or {}
    safety_ok = (
        witness.returncode == 7
        and safety.returncode == 1
        and safety_run.get("state") == "failed"
        and "continuation_unfinished" in (safety_run.get("diagnostics") or [])
    )
    h.note(safety_id, "continued failure without --finish triggers the safety net")

    reap = h.helper("retention", {"apply": True}, env=world)
    reaped_triage = (h.show(agent_id, env=world).get("triage") or {})
    reaped_ok = (
        reap.get("owner") == "tool_run_retention"
        and reap.get("mode") == "apply"
        and reap.get("owner_error") is None
        and reaped_triage.get("verdict") == "no_new_failures"
        and bool(reaped_triage.get("items"))
    )

    failures = h.run(["tool", "failures", "-j", "-t", "check"], env=world, cwd=project)
    try:
        groups = json.loads(failures.stdout).get("groups") or []
    except json.JSONDecodeError:
        groups = []
    failures_ok = failures.returncode == 0 and any(
        group.get("tool") == "check" for group in groups if isinstance(group, dict)
    )

    return [
        case(
            "dod-7-triage-known",
            known_ok,
            dod=["DoD-7"],
            run_ids=[seed_id, agent_id],
            continued=len(continued),
            verdict=triage.get("verdict"),
            stages=stages,
        ),
        case(
            "dod-7-triage-new",
            new_ok,
            dod=["DoD-7"],
            run_ids=[new_id],
            stopped_reason=stopped[0].get("reason") if stopped else None,
        ),
        case(
            "dod-7-triage-exit-parity",
            seed.returncode == agent.returncode == 7,
            dod=["DoD-7"],
            run_ids=[seed_id, agent_id],
            fail_fast_exit=seed.returncode,
            continued_exit=agent.returncode,
        ),
        case(
            "dod-7-triage-safety-net",
            safety_ok,
            dod=["DoD-7"],
            run_ids=[safety_id],
            exit_code=safety.returncode,
            diagnostics=safety_run.get("diagnostics"),
        ),
        case(
            "dod-2-triage-show-after-reap",
            reaped_ok,
            dod=["DoD-2"],
            run_ids=[agent_id],
            verdict=reaped_triage.get("verdict"),
            item_count=len(reaped_triage.get("items") or []),
            reap_changed=reap.get("changed"),
            reap_mode=reap.get("mode"),
        ),
        case(
            "dod-9-triage-failures",
            failures_ok,
            dod=["DoD-9"],
            run_ids=[agent_id],
            group_count=len(groups),
        ),
    ]
