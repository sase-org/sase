"""Unit tests for the Claude helper PreToolUse guard.

The guard runs as ``<sys.executable> -I <guard path>`` in production, so
these tests invoke it the same way: each case spawns the real script with
a JSON payload on stdin and asserts on the exit code and stdout.
"""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

import pytest

from sase.llm_provider._claude_helper_guard import (
    GUARD_DENY_REASON_PREFIX,
    ROOT_ONLY_SKILLS,
)

GUARD_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "sase"
    / "llm_provider"
    / "_claude_helper_guard.py"
)


def _run_guard(payload: object) -> tuple[int, str]:
    """Run the guard script with *payload* as stdin; return (exit, stdout)."""
    if isinstance(payload, str):
        raw = payload
    else:
        raw = json.dumps(payload)
    result = subprocess.run(
        [sys.executable, "-I", str(GUARD_PATH)],
        input=raw,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return result.returncode, result.stdout


def _bash_payload(command: object, *, agent_id: object = "agent-1") -> dict:
    payload: dict = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }
    if agent_id is not None:
        payload["agent_id"] = agent_id
    return payload


def _deny_reason(stdout: str) -> str:
    body = json.loads(stdout)
    return str(
        body["hookSpecificOutput"]["permissionDecisionReason"],
    )


def test_guard_script_is_stdlib_only() -> None:
    """The guard must stay importable without ``sase`` on the path."""
    assert GUARD_PATH.is_file()
    source = GUARD_PATH.read_text(encoding="utf-8")
    assert "import sase" not in source
    assert "from sase" not in source


@pytest.mark.parametrize(
    "command",
    [
        "sase final submit x.json",
        "sase final prepare x.json",
        "sase final defer x.json",
        "sase final context -f json",
        ".venv/bin/sase final prepare x",
        "FOO=1 sase final submit",
        "/opt/venv/bin/sase final submit",
    ],
)
def test_helper_final_mutations_are_denied(command: str) -> None:
    exit_code, stdout = _run_guard(_bash_payload(command))
    assert exit_code == 0
    assert json.loads(stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert _deny_reason(stdout).startswith(GUARD_DENY_REASON_PREFIX)


@pytest.mark.parametrize(
    "command",
    [
        "sase plan propose sase_plan_x.md",
        "sase monitor start -p verify -f run-1 -- just check",
        "sase launch request -f launch_request.json -o json",
        "sase pipe 'keep going' --reason 'handoff'",
        "sase gate create --turn --query q",
        "sase gate wait gate-1",
        'sase questions \'[{"question": "Q?"}]\'',
        "sase run",
        "sase run -d",
        "sase sudo request",
        "sase stitch create",
    ],
)
def test_helper_turn_ending_forms_are_denied(command: str) -> None:
    exit_code, stdout = _run_guard(_bash_payload(command))
    assert exit_code == 0
    assert json.loads(stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert _deny_reason(stdout).startswith(GUARD_DENY_REASON_PREFIX)


@pytest.mark.parametrize(
    "command",
    [
        "sase final status run-1",
        "sase final list",
        "sase final show run-1",
        "sase final doctor",
        "sase plan validate sase_plan_x.md",
        "sase monitor show run-1 --all-lines",
        "sase bead list",
        "sase memory read sase.md -r 'why'",
        "ls -la",
        "echo 'sase final submit'",
    ],
)
def test_helper_benign_commands_are_allowed(command: str) -> None:
    exit_code, stdout = _run_guard(_bash_payload(command))
    assert exit_code == 0
    assert stdout == ""


def test_helper_chained_violation_is_denied() -> None:
    exit_code, stdout = _run_guard(_bash_payload("echo ok && sase final submit x"))
    assert exit_code == 0
    assert json.loads(stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.parametrize("agent_id", [None, "", "   "])
def test_root_input_is_never_denied(agent_id: object) -> None:
    """Calls without a real ``agent_id`` are the root's own: always allow."""
    payload = _bash_payload("sase final submit x.json", agent_id=agent_id)
    if agent_id is None:
        assert "agent_id" not in payload
    exit_code, stdout = _run_guard(payload)
    assert exit_code == 0
    assert stdout == ""


@pytest.mark.parametrize("skill", sorted(ROOT_ONLY_SKILLS))
def test_helper_root_only_skills_are_denied(skill: str) -> None:
    exit_code, stdout = _run_guard(
        {
            "agent_id": "agent-1",
            "tool_name": "Skill",
            "tool_input": {"skill": skill},
        }
    )
    assert exit_code == 0
    assert json.loads(stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert _deny_reason(stdout).startswith(GUARD_DENY_REASON_PREFIX)


@pytest.mark.parametrize("skill", ["sase_memory_read", "sase_repo", "commit"])
def test_helper_other_skills_are_allowed(skill: str) -> None:
    exit_code, stdout = _run_guard(
        {
            "agent_id": "agent-1",
            "tool_name": "Skill",
            "tool_input": {"skill": skill},
        }
    )
    assert exit_code == 0
    assert stdout == ""


def test_helper_other_tools_are_allowed() -> None:
    exit_code, stdout = _run_guard(
        {
            "agent_id": "agent-1",
            "tool_name": "Read",
            "tool_input": {"file_path": "/tmp/x"},
        }
    )
    assert exit_code == 0
    assert stdout == ""


@pytest.mark.parametrize(
    "raw",
    ["", "not json", "[1, 2]", "42", "null"],
)
def test_malformed_stdin_exits_zero_silently(raw: str) -> None:
    exit_code, stdout = _run_guard(raw)
    assert exit_code == 0
    assert stdout == ""


def test_guard_p95_latency() -> None:
    """The hook runs on every Bash/Skill call; p95 must stay well under 1s."""
    payload = json.dumps(_bash_payload("ls"))
    samples: list[float] = []
    for _ in range(25):
        started = time.perf_counter()
        result = subprocess.run(
            [sys.executable, "-I", str(GUARD_PATH)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        samples.append(time.perf_counter() - started)
        assert result.returncode == 0
    samples.sort()
    p95 = samples[min(len(samples) - 1, int(len(samples) * 0.95))]
    mean = statistics.fmean(samples)
    print(f"\nguard latency: mean={mean * 1000:.1f}ms p95={p95 * 1000:.1f}ms")
    assert p95 < 1.0
