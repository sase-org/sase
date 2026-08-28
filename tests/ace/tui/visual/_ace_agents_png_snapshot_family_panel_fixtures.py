"""Family fixtures shared by family panel PNG visual snapshot tests."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from sase.ace.tui.models._agent_ordering import sort_and_reorder
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import _apply_status_overrides
from sase.gate_shell.state import gate_state_bucket
from sase.monitor_state import monitor_state_bucket

_FAMILY_NAME = "visual-family"
_STARTED = datetime(2026, 7, 18, 13, 0, 0)


def _write_phase_content(directory: Path, role: str) -> None:
    directory.mkdir()
    (directory / "raw_xprompt.md").write_text(
        "\n".join(f"#{role} family xprompt line {index}" for index in range(1, 16))
        + "\n",
        encoding="utf-8",
    )
    (directory / "01_prompt.md").write_text(
        "\n".join(f"{role} prompt line {index}" for index in range(1, 16)) + "\n",
        encoding="utf-8",
    )
    (directory / "response.md").write_text(
        "\n".join(f"{role} reply line {index}" for index in range(1, 7)) + "\n",
        encoding="utf-8",
    )


def _family_agents(
    tmp_path: Path,
    *,
    member_count: int,
    with_content: bool,
    with_monitor: bool = False,
    monitor_command: str = "just check-full",
    monitor_reason: str = "Full-suite verification before landing",
) -> list[Agent]:
    assert member_count >= 2
    root_dir = tmp_path / "family-plan"
    if with_content:
        _write_phase_content(root_dir, "plan")
    root = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-family-root",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=_STARTED,
        stop_time=_STARTED + timedelta(minutes=2),
        raw_suffix="20260718130000-family-plan",
        artifacts_dir=str(root_dir) if with_content else None,
        response_path=str(root_dir / "response.md") if with_content else None,
        role_suffix="--plan",
        agent_name=f"{_FAMILY_NAME}--plan",
        agent_family=_FAMILY_NAME,
        agent_family_role="plan",
        plan_chain_root=True,
        output_variables={"plan_path": "/workspace/sase/plans/family.md"},
        workspace_num=4,
        llm_provider="claude",
        model="opus",
    )
    rows = [root]
    for index in range(1, member_count):
        role = "code" if index == 1 else ("reviewer" if index == 2 else "phase")
        suffix = f"--{role}" if index < 3 else f"--phase-{index:02d}"
        phase_dir = tmp_path / f"family-{index:02d}"
        if with_content:
            _write_phase_content(phase_dir, role)
        started = _STARTED + timedelta(minutes=index * 2)
        rows.append(
            Agent(
                agent_type=AgentType.RUNNING,
                cl_name=f"visual-family-{index:02d}",
                project_file="/workspace/sase/visual_project.sase",
                status="DONE",
                start_time=started,
                stop_time=started + timedelta(minutes=2),
                raw_suffix=f"2026071813{index * 2:02d}00-family-{index:02d}",
                parent_timestamp=root.raw_suffix,
                artifacts_dir=str(phase_dir) if with_content else None,
                response_path=(
                    str(phase_dir / "response.md") if with_content else None
                ),
                role_suffix=suffix,
                agent_name=f"{_FAMILY_NAME}{suffix}",
                agent_family=_FAMILY_NAME,
                agent_family_role=role,
                activity=(
                    "implementing numbered navigation"
                    if index == 1
                    else "reviewing fold alignment"
                ),
                output_variables={
                    f"phase_{index}_report": f"/workspace/sase/out/phase-{index}.md"
                },
                workspace_num=4 + index,
                llm_provider="codex",
                model="gpt-5",
            )
        )
    if with_monitor:
        mon_dir = tmp_path / "family-monitor"
        mon_dir.mkdir()
        (mon_dir / "live_reply.md").write_text(
            "✓ lint (ruff)\nFAILED tests/ace/tui/test_x.py::test_y\n",
            encoding="utf-8",
        )
        starter = rows[-1]
        mon_started = _STARTED + timedelta(minutes=member_count * 2)
        rows.append(
            Agent(
                agent_type=AgentType.RUNNING,
                cl_name="visual-family-mon",
                project_file="/workspace/sase/visual_project.sase",
                status="MONITORED",
                status_bucket=monitor_state_bucket("completed"),
                start_time=mon_started,
                stop_time=mon_started + timedelta(minutes=1),
                raw_suffix="20260718131200-family-mon",
                parent_timestamp=starter.raw_suffix,
                artifacts_dir=str(mon_dir),
                role_suffix="--mon",
                agent_name=f"{_FAMILY_NAME}--mon",
                agent_family=_FAMILY_NAME,
                agent_family_role="monitor",
                monitor_id="gh6fddk5v3g9",
                monitor_state="completed",
                monitor_start_status="MONITORING",
                monitor_stop_status="MONITORED",
                monitor_label="just check",
                monitor_command=monitor_command,
                monitor_cwd="/workspace/sase",
                monitor_reason=monitor_reason,
                monitor_next_action="Report pass/fail to the user.",
                monitor_exit_code=1,
                monitor_timeout_seconds=2700.0,
                workspace_num=4 + member_count,
            )
        )
    _apply_status_overrides(rows)
    return sort_and_reorder(rows, [])


def _gate_family_agents(tmp_path: Path) -> list[Agent]:
    rows = _family_agents(tmp_path, member_count=2, with_content=False)
    starter = next(row for row in rows if row.agent_family_role == "code")
    gate_root = tmp_path / "family-gates"
    gate_root.mkdir()
    output_path = gate_root / "run-output.log"
    output_path.write_text(
        "\n".join(
            f"gate output line {index:02d}: validated shard {index}"
            for index in range(1, 24)
        )
        + "\n",
        encoding="utf-8",
    )

    def gate(
        slug: str,
        *,
        state: str,
        start_status: str,
        stop_status: str,
        label: str,
        minutes: int,
        output: Path | None = None,
        truncated: bool = False,
        followup_error: str | None = None,
    ) -> Agent:
        started = _STARTED + timedelta(minutes=minutes)
        terminal = state in {
            "answered",
            "completed",
            "failed",
            "timeout",
            "stopped",
            "lost",
        }
        return Agent(
            agent_type=AgentType.RUNNING,
            cl_name=f"visual-gate-{slug}",
            project_file="/workspace/sase/visual_project.sase",
            status=stop_status if terminal else start_status,
            status_bucket=gate_state_bucket(state),
            start_time=started,
            run_start_time=started,
            stop_time=started + timedelta(minutes=1) if terminal else None,
            raw_suffix=f"2026071813{minutes:02d}00-family-gate-{slug}",
            parent_timestamp=starter.raw_suffix,
            role_suffix=f"--gate-{slug}",
            agent_name=f"{_FAMILY_NAME}--gate-{slug}",
            agent_family=_FAMILY_NAME,
            agent_family_role="gate",
            gate_id=f"gate-{slug}-visual-1234567890",
            gate_kind="approval",
            gate_state=state,
            gate_start_status=start_status,
            gate_stop_status=stop_status,
            gate_accent="#0BCDEC",
            gate_label=label,
            gate_reason="Human confirmation before the next family shell",
            gate_timeout_seconds=2700.0,
            gate_elapsed_seconds=75.0 if terminal else 35.0,
            gate_output_path=str(output) if output is not None else None,
            gate_output_truncated=truncated,
            gate_bundle_path=f"/workspace/sase/family-gates/{slug}",
            gate_decision_path=f"/workspace/sase/family-gates/{slug}/response.json",
            gate_next_action="Continue with the selected branch.",
            gate_followup_outcome="not-launchable" if followup_error else None,
            gate_followup_error=followup_error,
            workspace_num=8 + minutes,
        )

    rows.extend(
        [
            gate(
                "pending",
                state="pending",
                start_status="WAITING",
                stop_status="ANSWERED",
                label="Approve plan handoff",
                minutes=6,
            ),
            gate(
                "run",
                state="settling",
                start_status="RUNNING",
                stop_status="SETTLED",
                label="Run deployment preview",
                minutes=7,
                output=output_path,
                truncated=True,
            ),
            gate(
                "answered",
                state="answered",
                start_status="WAITING",
                stop_status="APPROVED",
                label="Accept reviewer branch",
                minutes=8,
            ),
            gate(
                "failed",
                state="failed",
                start_status="RUNNING",
                stop_status="FAILED",
                label="Apply cleanup branch",
                minutes=9,
                followup_error="Selected branch could not launch",
            ),
        ]
    )
    _apply_status_overrides(rows)
    return sort_and_reorder(rows, [])


def _selected_gate_agent(tmp_path: Path) -> Agent:
    gate = next(
        row for row in _gate_family_agents(tmp_path) if row.cl_name == "visual-gate-run"
    )
    gate.cl_name = "visual-standalone-gate-run"
    gate.raw_suffix = "20260718130700-standalone-gate-run"
    gate.parent_timestamp = None
    gate.agent_family = "visual-standalone-gate"
    gate.agent_name = "visual-standalone-gate--gate-run"
    return gate
