"""Tree and layout data builders for AXE PNG snapshot tests."""

from __future__ import annotations

import dataclasses

from sase.ace.tui.actions.axe_display._data import (
    AxeCollectedData,
    BgCmdSnapshot,
    ChopSnapshot,
    LumberjackSnapshot,
)
from sase.service.status import (
    ServiceEnablement,
    ServiceStatusHost,
    ServiceStatusProc,
    ServiceStatusSnapshot,
)
from sase.ace.tui.bgcmd import BackgroundCommandInfo
from sase.axe.state import LumberjackMetrics
from tests.ace.tui.visual._ace_axe_png_snapshot_builders import (
    make_chop_run,
    make_lumberjack_status,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import axe_collected_data


def axe_bgcmd_data() -> AxeCollectedData:
    info_a = BackgroundCommandInfo(
        command="just test --visual",
        project="visual_project",
        workspace_num=1,
        workspace_dir="/workspace/sase_1",
        started_at="2026-07-06T11:58:00",
        pid=12345,
        proc_id="proc-a",
        status="running",
    )
    info_b = BackgroundCommandInfo(
        command="just check",
        project="visual_project",
        workspace_num=2,
        workspace_dir="/workspace/sase_2",
        started_at="2026-07-06T11:50:00",
        pid=None,
        finished_at="2026-07-06T11:56:00",
        proc_id="proc-b",
        status="success",
        exit_code=0,
    )
    slots = [(1, info_a), (2, info_b)]
    details = {
        1: BgCmdSnapshot(info=info_a, running=True, output_tail="running tests..."),
        2: BgCmdSnapshot(info=info_b, running=False, output_tail="check passed"),
    }
    return axe_collected_data(bgcmd_slots=slots, bgcmd_details=details)


def axe_lumberjack_tree_data() -> AxeCollectedData:
    """Build lumberjacks with chops alongside a background-command row."""
    fast_summary = "Run fast lint checks across changed Python files"
    fast_body = (
        "Checks the focused Python changes before the slower validation lane runs.\n\n"
        "- Reports lint failures beside the selected chop output.\n"
        "- Leaves full type checking to the slow_typecheck chop."
    )
    hooks_fast = ChopSnapshot(
        lumberjack_name="hooks",
        chop_name="fast_lint",
        description=f"{fast_summary}\n\n{fast_body}",
        description_summary=fast_summary,
        description_body=fast_body,
        runs=[
            make_chop_run(
                "hooks",
                "fast_lint",
                run_id="20260509T100100_000000",
                status="success",
            ),
        ],
    )
    hooks_slow = ChopSnapshot(
        lumberjack_name="hooks",
        chop_name="slow_typecheck",
        description="Run the complete static type-checking suite",
        runs=[
            make_chop_run(
                "hooks",
                "slow_typecheck",
                run_id="20260509T100000_000000",
                status="failure",
            ),
        ],
    )
    checks_smoke = ChopSnapshot(
        lumberjack_name="checks",
        chop_name="smoke",
        description="Run a quick smoke test before slower checks",
        runs=[],
    )
    chop_snapshots = {
        ("hooks", "fast_lint"): hooks_fast,
        ("hooks", "slow_typecheck"): hooks_slow,
        ("checks", "smoke"): checks_smoke,
    }
    hooks_status = make_lumberjack_status(
        "hooks", chops=["fast_lint", "slow_typecheck"]
    )
    checks_status = make_lumberjack_status("checks", status="stopped", chops=["smoke"])
    metrics = LumberjackMetrics(
        cycles_run=12, chops_executed=24, total_updates=12, errors_encountered=1
    )
    lumberjack_snapshots = {
        "hooks": LumberjackSnapshot(
            name="hooks",
            description=(
                "Fast lane that advances hook, mentor, and workflow lifecycle state\n\n"
                "Runs every few seconds to move completed lifecycle work forward while "
                "keeping slower repository checks in their own lane.\n\n"
                "- Includes hook, mentor, and workflow state transitions.\n"
                "- Excludes submission and workspace audits."
            ),
            description_summary=(
                "Fast lane that advances hook, mentor, and workflow lifecycle state"
            ),
            description_body=(
                "Runs every few seconds to move completed lifecycle work forward while "
                "keeping slower repository checks in their own lane.\n\n"
                "- Includes hook, mentor, and workflow state transitions.\n"
                "- Excludes submission and workspace audits."
            ),
            status=hooks_status,
            metrics=metrics,
            log_tail="",
            chops=[hooks_fast, hooks_slow],
        ),
        "checks": LumberjackSnapshot(
            name="checks",
            description="Poll slower submission and workspace checks",
            status=checks_status,
            metrics=metrics,
            log_tail="",
            chops=[checks_smoke],
        ),
    }
    bgcmd_info = BackgroundCommandInfo(
        command="just check",
        project="visual_project",
        workspace_num=1,
        workspace_dir="/workspace/sase_1",
        started_at="2026-07-06T11:57:00",
        pid=12345,
        proc_id="proc-tree",
        status="running",
    )
    return axe_collected_data(
        lumberjack_names=["hooks", "checks"],
        lumberjack_statuses={"hooks": hooks_status, "checks": checks_status},
        lumberjack_metrics={"hooks": metrics, "checks": metrics},
        lumberjack_log_tails={"hooks": "", "checks": ""},
        lumberjack_chop_names={
            "hooks": ["fast_lint", "slow_typecheck"],
            "checks": ["smoke"],
        },
        chop_snapshots=chop_snapshots,
        lumberjack_snapshots=lumberjack_snapshots,
        bgcmd_slots=[(1, bgcmd_info)],
        bgcmd_details={
            1: BgCmdSnapshot(info=bgcmd_info, running=True, output_tail="building...")
        },
    )


def _services_panels_proc(
    name: str,
    state: str,
    *,
    desired: str = "running",
    available: bool = True,
    enabled: bool = True,
    enablement_summary: str = "enabled",
    summary: str = "",
    restarts: int = 0,
) -> ServiceStatusProc:
    return ServiceStatusProc(
        name=name,
        source="builtin",
        declared_by="builtin",
        mode="daemon",
        available=available,
        enablement=ServiceEnablement(
            enabled=enabled, provenance="builtin", summary=enablement_summary
        ),
        desired=desired,
        state=state,
        summary=summary or state,
        restarts=restarts,
    )


def _services_panels_status(
    *, scheduler_state: str = "running"
) -> ServiceStatusSnapshot:
    return ServiceStatusSnapshot(
        schema_version=1,
        generated_at=0.0,
        change_token="visual-services-panels",
        host=ServiceStatusHost(state="running", summary="running"),
        procs=(
            _services_panels_proc("scheduler", scheduler_state),
            _services_panels_proc("telegram", "running"),
            _services_panels_proc(
                "agents_sync",
                "crash_loop",
                summary="crash-looping",
                restarts=0 if scheduler_state != "running" else 3,
            ),
            _services_panels_proc(
                "web",
                "stopped",
                desired="stopped",
                enabled=False,
                enablement_summary="disabled here",
                summary="stopped",
            ),
        ),
        orphans=(),
        diagnostics=(),
    )


def services_panels_data() -> AxeCollectedData:
    """Services sidebar fixture: realistic service status plus routines/jobs.

    The host is running. The procs are scheduler running, telegram running,
    agents_sync ``crash_loop`` with 3 restarts, and a disabled proc. Two
    oneshots (one running, one exit 0) sit below the daemons, and the
    routine/job tree matches :func:`axe_lumberjack_tree_data`.
    """
    base = axe_lumberjack_tree_data()
    running_info = BackgroundCommandInfo(
        command="just check --all-targets",
        project="visual_project",
        workspace_num=1,
        workspace_dir="/workspace/sase_1",
        started_at="2026-07-06T11:57:00",
        pid=12345,
        proc_id="proc-panels-run",
        status="running",
    )
    done_info = BackgroundCommandInfo(
        command="make docs",
        project="visual_project",
        workspace_num=2,
        workspace_dir="/workspace/sase_2",
        started_at="2026-07-06T11:50:00",
        pid=None,
        finished_at="2026-07-06T11:56:00",
        proc_id="proc-panels-done",
        status="success",
        exit_code=0,
    )
    return dataclasses.replace(
        base,
        bgcmd_slots=[(1, running_info), (2, done_info)],
        bgcmd_details={
            1: BgCmdSnapshot(
                info=running_info, running=True, output_tail="checking..."
            ),
            2: BgCmdSnapshot(info=done_info, running=False, output_tail="docs built"),
        },
        service_status=_services_panels_status(),
    )


def services_panels_empty_routines_data() -> AxeCollectedData:
    """Services sidebar with no routines, a stopped scheduler, and oneshots."""
    base = services_panels_data()
    return dataclasses.replace(
        base,
        lumberjack_names=[],
        lumberjack_statuses={},
        lumberjack_metrics={},
        lumberjack_log_tails={},
        lumberjack_chop_names={},
        chop_snapshots={},
        lumberjack_snapshots={},
        service_status=_services_panels_status(scheduler_state="stopped"),
    )


def axe_description_overflow_data() -> AxeCollectedData:
    data = axe_lumberjack_tree_data()
    chop = data.chop_snapshots[("hooks", "fast_lint")]
    chop.description_body = "\n\n".join(
        f"Paragraph {index} explains one more operational constraint."
        for index in range(1, 21)
    )
    chop.description = f"{chop.description_summary}\n\n{chop.description_body}"
    return data


def axe_disabled_chop_data() -> AxeCollectedData:
    """Build a configured but disabled chop that remains visible in the tree."""
    disabled = ChopSnapshot(
        lumberjack_name="hooks",
        chop_name="slow_typecheck",
        description="slow typecheck",
        runs=[],
        enabled=False,
        script="sase_chop_typecheck",
        resolved_path=None,
        config_status="disabled",
    )
    active = ChopSnapshot(
        lumberjack_name="hooks",
        chop_name="fast_lint",
        description="fast lint",
        runs=[
            make_chop_run(
                "hooks",
                "fast_lint",
                run_id="20260509T100100_000000",
                status="success",
            )
        ],
        script="sase_chop_lint",
    )
    hooks_status = make_lumberjack_status(
        "hooks", chops=["fast_lint", "slow_typecheck"]
    )
    metrics = LumberjackMetrics(
        cycles_run=8, chops_executed=15, total_updates=8, errors_encountered=0
    )
    return axe_collected_data(
        lumberjack_names=["hooks"],
        lumberjack_statuses={"hooks": hooks_status},
        lumberjack_metrics={"hooks": metrics},
        lumberjack_log_tails={"hooks": ""},
        lumberjack_chop_names={"hooks": ["fast_lint", "slow_typecheck"]},
        chop_snapshots={
            ("hooks", "fast_lint"): active,
            ("hooks", "slow_typecheck"): disabled,
        },
        lumberjack_snapshots={
            "hooks": LumberjackSnapshot(
                name="hooks",
                status=hooks_status,
                metrics=metrics,
                log_tail="",
                chops=[active, disabled],
            ),
        },
    )


def axe_long_label_data() -> AxeCollectedData:
    """Build long lumberjack and chop labels that widen the sidebar."""
    chop_name = "review_pipeline_blocking_typecheck_long"
    lumberjack_name = "review_pipeline_blocking_long_name"
    chop = ChopSnapshot(
        lumberjack_name=lumberjack_name,
        chop_name=chop_name,
        description="long-named typecheck chop",
        runs=[
            make_chop_run(
                lumberjack_name,
                chop_name,
                run_id="20260509T100100_000000",
                status="success",
            ),
        ],
    )
    status = make_lumberjack_status(lumberjack_name, chops=[chop_name])
    metrics = LumberjackMetrics(
        cycles_run=12, chops_executed=24, total_updates=12, errors_encountered=0
    )
    bgcmd_info = BackgroundCommandInfo(
        command="just test --visual --snapshot --update --strict --verbose",
        project="visual_project",
        workspace_num=1,
        workspace_dir="/workspace/sase_1",
        started_at="2026-07-06T11:59:00",
        pid=12345,
        proc_id="proc-long",
        status="running",
    )
    return axe_collected_data(
        lumberjack_names=[lumberjack_name],
        lumberjack_statuses={lumberjack_name: status},
        lumberjack_metrics={lumberjack_name: metrics},
        lumberjack_log_tails={lumberjack_name: ""},
        lumberjack_chop_names={lumberjack_name: [chop_name]},
        chop_snapshots={(lumberjack_name, chop_name): chop},
        lumberjack_snapshots={
            lumberjack_name: LumberjackSnapshot(
                name=lumberjack_name,
                status=status,
                metrics=metrics,
                log_tail="",
                chops=[chop],
            ),
        },
        bgcmd_slots=[(1, bgcmd_info)],
        bgcmd_details={
            1: BgCmdSnapshot(
                info=bgcmd_info, running=True, output_tail="running tests..."
            )
        },
    )
