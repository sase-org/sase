"""Shared helpers for machine-capacity report feed tests."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime

from sase.ace.tui.actions.event_refresh._auto_refresh import (
    _CapacityReportFeedMixin,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.config.runner_limit_override import EffectiveRunnerLimitSnapshot
from sase.core.runner_slots import MachineCapacityReport, MachineCapacityRecordInputs


def make_agent(name: str, **overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": name,
        "project_file": "/tmp/project/project.sase",
        "status": "WAITING",
        "start_time": datetime(2026, 7, 12, 12, 0),
        "raw_suffix": name,
        "pid": 100,
        "artifacts_dir": f"/tmp/project/artifacts/ace-run/{name}",
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


def make_report(
    *,
    occupied: float = 5.0,
    claims: tuple[dict[str, object], ...] | None = None,
    waiters: tuple[dict[str, object], ...] = (),
) -> MachineCapacityReport:
    now = time.time()
    report_claims = claims or (
        {
            "owner_key": "claim-worker",
            "owner_artifact_dir": "/tmp/project/artifacts/worker",
            "artifact_dirs": ["/tmp/project/artifacts/worker"],
            "occupied_capacity": 1.0,
        },
    )
    accounting = (
        {
            "artifact_dir": "/tmp/project/artifacts/verify",
            "agent_name": "verify-monitor",
            "state": "holding",
            "charged_weight": 1.0,
            "claim_owner_key": "claim-verify",
        },
        {
            "artifact_dir": "/tmp/project/artifacts/wait-zero",
            "agent_name": "wait-monitor",
            "state": "holding",
            "charged_weight": 0.0,
            "claim_owner_key": "claim-zero",
        },
    )
    raw = {
        "occupied_capacity": occupied,
        "occupied_lanes": 6,
        "effective_limit": 8.0,
        "claims": list(report_claims),
        "waiters": list(waiters),
        "accounting": list(accounting),
        "accounting_valid": True,
    }
    return MachineCapacityReport(
        machine="athena",
        computed_at=now,
        scanned_at=now,
        token="capacity-token-1",
        scan_current=True,
        effective_limit=8.0,
        limit=EffectiveRunnerLimitSnapshot(
            configured_limit=8,
            temporary_override=None,
            captured_at=now,
        ),
        occupied_capacity=occupied,
        occupied_lanes=6,
        over_limit=False,
        claims=tuple(report_claims),
        waiters=waiters,
        accounting=accounting,
        diagnostics=(),
        accounting_valid=True,
        accounting_available=True,
        raw_snapshot=raw,
        record_inputs=(
            MachineCapacityRecordInputs(
                artifact_dir="/tmp/project/artifacts/verify",
                turn_kind="monitor",
                turn_role="monitor",
                monitor_id="verify-1",
                slot_requested_at=None,
                authored_queue_capacity=None,
                run_started_at=None,
            ),
        ),
    )


class FeedApp(_CapacityReportFeedMixin):
    def __init__(self, report_source: object) -> None:
        self._machine_capacity_report_source = report_source
        self._capacity_reports_installed: asyncio.Queue[MachineCapacityReport] = (
            asyncio.Queue()
        )
        self._machine_capacity_token_probe = lambda: "token"
        self.current_tab = "agents"
        self._agents_first_load_done = False
        self._machine_capacity_refresh_generation = 0
        self._machine_capacity_refresh_scheduled = False
        self._machine_capacity_refresh_running = False
        self._machine_capacity_refresh_pending = False
        self._machine_capacity_report_generation = 0
        self._machine_capacity_report_mono = 0.0
        self._machine_capacity_feed_tasks: set[asyncio.Task[object]] = set()
        self._capacity_telemetry_tasks: set[asyncio.Task[object]] = set()
        self._telemetry_records: list[dict[str, object]] = []
        self._schedule_capacity_telemetry_write = self._telemetry_records.append

    def _update_agents_info_panel(self) -> None:
        pass

    def _bump_agents_capacity_generation(self) -> int:
        return 1

    def _install_machine_capacity_report(self, report: MachineCapacityReport) -> None:
        super()._install_machine_capacity_report(report)
        self._capacity_reports_installed.put_nowait(report)
