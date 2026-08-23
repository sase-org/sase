"""Shared helpers for ``sase monitor`` handler tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.main.monitor_handler import handle_monitor_command
from tests.main.parser_cli_helpers import parse_sase_args
from tests.monitor._fixtures import make_starter_agent, patch_project_records

__all__ = [
    "dispatch",
    "make_monitor",
    "monitor_home",
    "patch_project_records",
    "pin_project",
]


@pytest.fixture(autouse=True)
def monitor_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point every agent-artifact path this handler reads at an isolated home."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SASE_HOME", str(home))
    return home


def pin_project(monkeypatch: pytest.MonkeyPatch, project: str = "proj") -> None:
    """Force the handler to treat the cwd as belonging to ``project``."""
    monkeypatch.setattr(
        "sase.main.monitor_handler._infer_project_name", lambda _cwd: project
    )


def dispatch(argv: list[str]) -> int:
    """Run one ``sase monitor`` invocation and return its process exit code."""
    with pytest.raises(SystemExit) as exit_info:
        handle_monitor_command(parse_sase_args(argv))
    return int(exit_info.value.code or 0)


def make_monitor(
    project: str,
    timestamp: str,
    member_name: str,
    *,
    lane: str,
    monitor_id: str,
    monitor_state: str = "running",
    command: str = "just check",
    reason: str = "verify",
    label: str | None = None,
    cwd: str = "/tmp/work",
    start_status: str = "MONITORING",
    stop_status: str = "MONITORED",
    timeout_seconds: float = 60.0,
    tail_lines: int = 200,
    exit_code: int | None = None,
    next_action: str | None = None,
    pid: int | None = None,
    **overrides: object,
) -> str:
    """Create a real monitor member's artifacts dir with test-friendly defaults."""
    meta: dict[str, object] = {
        "agent_family": lane,
        "agent_family_role": "monitor",
        "monitor_id": monitor_id,
        "monitor_state": monitor_state,
        "monitor_settled": monitor_state != "running",
        "monitor_command": command,
        "monitor_cwd": cwd,
        "monitor_reason": reason,
        "monitor_label": label or command,
        "monitor_start_status": start_status,
        "monitor_stop_status": stop_status,
        "monitor_timeout_seconds": timeout_seconds,
        "monitor_tail_lines": tail_lines,
    }
    if exit_code is not None:
        meta["monitor_exit_code"] = exit_code
    if next_action:
        meta["monitor_next_action"] = next_action
    if pid is not None:
        meta["pid"] = pid
    meta.update(overrides)
    return make_starter_agent(project, timestamp, member_name, **meta)
