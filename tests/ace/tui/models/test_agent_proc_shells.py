"""Agents-tab projection for stand-alone proc-shell records."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from sase.ace.tui._proc_observer_models import ObservedProc
from sase.ace.tui.actions.agents._display_panel_titles import agent_panel_counts
from sase.ace.tui.actions.agents._monitor_stop_flow import MonitorStopActionFlowMixin
from sase.ace.tui.models._agent_clan import sase_agent_status_counts
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_proc_shells import proc_shell_agents_from_observed
from sase.ace.tui.widgets._agent_list_render_agent import format_agent_option
from sase.ops.names import PROC_KILL
from sase.procs import PROC_LIFECYCLE_PROC_SHELL, XPROMPT_PROC_ORIGIN


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def _proc(
    proc_id: str = "abc123def456",
    *,
    status: str = "running",
    lifecycle: str = PROC_LIFECYCLE_PROC_SHELL,
    origin: str = XPROMPT_PROC_ORIGIN,
    label: str = "Build docs",
    xprompt_proc: dict[str, Any] | None = None,
) -> ObservedProc:
    return ObservedProc(
        proc_id=proc_id,
        proc_type="command",
        cl_name="sase",
        project_file="",
        status=status,
        message="",
        started_at=_dt("2026-08-20T12:00:02Z"),
        display_name=label,
        command=["bash", "-lc", "just docs"],
        cwd="/workspace/sase",
        origin=origin,
        log_path=f"/tmp/{proc_id}.log",
        lifecycle=lifecycle,
        project="sase",
        workspace_num=12,
        phase="execute",
        shell_name="agent--build",
        shell_kind="bash",
        timeout_seconds=600,
        idle_timeout_seconds=120,
        request_fingerprint="sha256:proc",
        supervisor_id="supervisor-1",
        output="ready\npassword=hunter2\ncomplete",
        xprompt_proc=xprompt_proc
        if xprompt_proc is not None
        else {
            "code_digest": "sha256:code",
            "code_language": "bash",
            "safe_preview": "echo ok\napi_key=hidden",
            "waits": [{"kind": "bead", "target": "sase-s6.7"}, "quiet"],
            "condition_result": {"status": "passed", "reason": "cache warm"},
        },
    )


def _patch_projection_io(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_proc_shells.project_display_name_for",
        lambda key: f"{key} display",
    )


def test_proc_shell_projection_selects_standalone_xprompt_procs_and_dedupes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_projection_io(monkeypatch)

    agents = proc_shell_agents_from_observed(
        [
            _proc(),
            _proc(label="duplicate"),
            _proc("legacy123456", lifecycle="legacy"),
            _proc("other123456", origin="ace"),
        ]
    )

    assert len(agents) == 1
    agent = agents[0]
    assert agent.agent_type is AgentType.PROC_SHELL
    assert agent.is_proc_shell
    assert agent.is_agent_entry is False
    assert agent.pid is None
    assert agent.proc_id == "abc123def456"
    assert agent.display_name == "Build docs"
    assert agent.proc_language == "bash"
    assert agent.proc_waits == ["bead: sase-s6.7", "quiet"]
    assert agent.proc_condition_result == "passed: cache warm"
    assert agent.project_display_name == "sase display"
    assert "<redacted sensitive line>" in (agent.proc_safe_preview or "")
    assert "<redacted sensitive line>" in (agent.proc_log_tail or "")
    assert "api_key" not in (agent.proc_safe_preview or "")
    assert "password" not in (agent.proc_log_tail or "")


@pytest.mark.parametrize(
    ("proc_status", "agent_status", "bucket"),
    [
        ("pending", "STARTING", "Starting"),
        ("running", "RUNNING", "Running"),
        ("settling", "SETTLING", "Running"),
        ("success", "DONE", "Done"),
        ("error", "FAILED", "Failed"),
        ("killed", "STOPPED", "Done"),
    ],
)
def test_proc_shell_projection_maps_proc_statuses(
    monkeypatch: pytest.MonkeyPatch,
    proc_status: str,
    agent_status: str,
    bucket: str,
) -> None:
    _patch_projection_io(monkeypatch)

    [agent] = proc_shell_agents_from_observed([_proc(status=proc_status)])

    assert agent.status == agent_status
    assert agent.status_bucket == bucket
    assert agent.proc_status == proc_status


def test_proc_shell_row_renders_identity_status_phase_and_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_projection_io(monkeypatch)
    [agent] = proc_shell_agents_from_observed([_proc()])

    left, _suffix, _option_id = format_agent_option(agent, 0, is_selected=False)

    assert "▣" in left.plain
    assert "Build docs" in left.plain
    assert "(RUNNING)" in left.plain
    assert "execute" in left.plain
    assert "[bash]" in left.plain
    assert "abc123" in left.plain


def test_proc_shell_counts_stay_out_of_agent_lanes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_projection_io(monkeypatch)
    [proc_agent] = proc_shell_agents_from_observed([_proc()])
    running_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sase",
        project_file="/repo/sase.sase",
        status="RUNNING",
        start_time=None,
        raw_suffix="agent-1",
    )

    summary = sase_agent_status_counts([running_agent, proc_agent], ())
    panel_counts = agent_panel_counts([running_agent, proc_agent], set())

    assert summary.total == 1
    assert summary.running == 1
    assert panel_counts.lane_count == 1
    assert panel_counts.proc_shells == 1


class _KillHost(MonitorStopActionFlowMixin):
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.notifications: list[tuple[str, str]] = []

    def _submit_durable_proc(self, argv: list[str], **kwargs: Any) -> None:
        self.calls.append({"argv": argv, **kwargs})

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))


def test_proc_shell_kill_dispatches_native_proc_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_projection_io(monkeypatch)
    host = _KillHost()
    [agent] = proc_shell_agents_from_observed([_proc()])

    host._do_kill_proc_shell(agent)

    assert host.notifications == []
    call = host.calls[0]
    assert call["argv"] == ["sase", "proc", "kill", "abc123def456", "--json"]
    assert call["operation"] == PROC_KILL
    assert call["proc_type"] == PROC_KILL
    assert call["request"] == {
        "proc_id": "abc123def456",
        "proc_label": "Build docs",
    }
    assert call["concurrency_keys"] == ("proc-kill:abc123def456",)
    assert call["label"] == "kill proc Build docs"
