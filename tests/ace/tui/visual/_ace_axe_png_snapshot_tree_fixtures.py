"""Tree and layout data builders for AXE PNG snapshot tests."""

from __future__ import annotations

import dataclasses

from sase.ace.tui.actions.axe_display._data import (
    AxeCollectedData,
    BgCmdSnapshot,
    ChopSnapshot,
    LumberjackSnapshot,
)
from sase.axe.config_backend import AxeEntityOrigin
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
    description: str | None = None,
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
        description=description,
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
            _services_panels_proc(
                "scheduler",
                scheduler_state,
                description=(
                    "Run SASE's background automation: routines and their scheduled jobs\n"
                    "\n"
                    "Runs the scheduler orchestrator for the visual snapshot.\n"
                    "\n"
                    "- Stopping it pauses scheduled automation.\n"
                    "- Configure the work under axe.routines."
                ),
            ),
            _services_panels_proc(
                "telegram",
                "running",
                description="Receive Telegram updates for remote agent dispatch.",
            ),
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


_VISUAL_USER_DECLARED_BY = "user:visual/sase.yml"
_VISUAL_PLUGIN_DECLARED_BY = "plugin:visual-acme"
_VISUAL_BUILTIN_DECLARED_BY = "default"


def _services_origin(source: str) -> AxeEntityOrigin:
    """Return the deterministic declaring origin for a Services ``source``."""
    if source == "user":
        return AxeEntityOrigin(source="user", declared_by=_VISUAL_USER_DECLARED_BY)
    if source == "plugin":
        return AxeEntityOrigin(source="plugin", declared_by=_VISUAL_PLUGIN_DECLARED_BY)
    if source == "builtin":
        return AxeEntityOrigin(
            source="builtin", declared_by=_VISUAL_BUILTIN_DECLARED_BY
        )
    raise ValueError(f"Unknown Services visual source {source!r}")


def _stamp_services_origins(
    base: AxeCollectedData, sources: dict[str, str]
) -> AxeCollectedData:
    """Stamp declaring origins onto routine/job snapshots and origin maps.

    ``sources`` maps routine name to ``user`` | ``plugin`` | ``builtin``.
    Snapshot ``source``/``declared_by`` fields and the ``routine_origins`` /
    ``chop_origins`` maps are set from the same values so the sidebar
    panels, titles, fold state, and health badges all agree.
    """
    chop_snapshots = dict(base.chop_snapshots)
    lumberjack_snapshots = dict(base.lumberjack_snapshots)
    routine_origins = dict(base.routine_origins)
    chop_origins = dict(base.chop_origins)
    for routine_name, source in sources.items():
        origin = _services_origin(source)
        routine_origins[routine_name] = origin
        snapshot = lumberjack_snapshots.get(routine_name)
        if snapshot is not None:
            lumberjack_snapshots[routine_name] = dataclasses.replace(
                snapshot, source=source, declared_by=origin.declared_by
            )
        for chop_name in base.lumberjack_chop_names.get(routine_name, []):
            key = (routine_name, chop_name)
            chop_origins[key] = origin
            chop = chop_snapshots.get(key)
            if chop is not None:
                chop_snapshots[key] = dataclasses.replace(
                    chop, source=source, declared_by=origin.declared_by
                )
    return dataclasses.replace(
        base,
        chop_snapshots=chop_snapshots,
        lumberjack_snapshots=lumberjack_snapshots,
        routine_origins=routine_origins,
        chop_origins=chop_origins,
    )


def _services_builtin_smoke_failure() -> ChopSnapshot:
    """Return the builtin ``checks/smoke`` chop with a failed newest run.

    The failure run drives the ``!1`` health badge on the collapsed
    builtin parent row.
    """
    return ChopSnapshot(
        lumberjack_name="checks",
        chop_name="smoke",
        description="Run a quick smoke test before slower checks",
        runs=[
            make_chop_run(
                "checks",
                "smoke",
                run_id="20260509T100200_000000",
                status="failure",
            ),
        ],
    )


def services_panels_data() -> AxeCollectedData:
    """Services sidebar fixture: Builtin+User source groups plus jobs.

    The host is running. The procs are scheduler running, telegram running,
    agents_sync ``crash_loop`` with 3 restarts, and a disabled proc. Two
    oneshots (one running, one exit 0) sit below the daemons. Routine
    ``hooks`` is user-declared (two jobs, one failed); routine ``checks``
    is builtin-declared with a failed ``smoke`` job so the folded builtin
    parent renders its ``!1`` health badge.
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
    chop_snapshots = dict(base.chop_snapshots)
    chop_snapshots[("checks", "smoke")] = _services_builtin_smoke_failure()
    base = dataclasses.replace(
        base,
        bgcmd_slots=[(1, running_info), (2, done_info)],
        bgcmd_details={
            1: BgCmdSnapshot(
                info=running_info, running=True, output_tail="checking..."
            ),
            2: BgCmdSnapshot(info=done_info, running=False, output_tail="docs built"),
        },
        chop_snapshots=chop_snapshots,
        service_status=_services_panels_status(),
    )
    return _stamp_services_origins(base, {"hooks": "user", "checks": "builtin"})


def services_panels_all_sources_data() -> AxeCollectedData:
    """Services sidebar fixture: User+Plugin+Builtin source groups.

    Extends :func:`services_panels_data` with the plugin-declared
    ``sentinels`` routine (one successful ``watch`` job) so all three
    routine panels render.
    """
    base = services_panels_data()
    watch = ChopSnapshot(
        lumberjack_name="sentinels",
        chop_name="watch",
        description="Watch the visual project for drift",
        runs=[
            make_chop_run(
                "sentinels",
                "watch",
                run_id="20260509T100300_000000",
                status="success",
            ),
        ],
    )
    status = make_lumberjack_status("sentinels", chops=["watch"])
    metrics = LumberjackMetrics(
        cycles_run=12, chops_executed=24, total_updates=12, errors_encountered=0
    )
    base = dataclasses.replace(
        base,
        lumberjack_names=["hooks", "sentinels", "checks"],
        lumberjack_statuses={**base.lumberjack_statuses, "sentinels": status},
        lumberjack_metrics={**base.lumberjack_metrics, "sentinels": metrics},
        lumberjack_log_tails={**base.lumberjack_log_tails, "sentinels": ""},
        lumberjack_chop_names={
            **base.lumberjack_chop_names,
            "sentinels": ["watch"],
        },
        chop_snapshots={**base.chop_snapshots, ("sentinels", "watch"): watch},
        lumberjack_snapshots={
            **base.lumberjack_snapshots,
            "sentinels": LumberjackSnapshot(
                name="sentinels",
                description="Watch the visual project for drift",
                description_summary="Watch the visual project for drift",
                description_body="",
                status=status,
                metrics=metrics,
                log_tail="",
                chops=[watch],
            ),
        },
    )
    return _stamp_services_origins(base, {"sentinels": "plugin"})


def services_panels_builtin_only_data() -> AxeCollectedData:
    """Services sidebar fixture: only the builtin ``checks`` routine.

    Keeps the failed ``smoke`` job so the folded builtin parent still
    renders its ``!1`` health badge with no user or plugin panels.
    """
    base = services_panels_data()
    return dataclasses.replace(
        base,
        lumberjack_names=["checks"],
        lumberjack_statuses={
            name: status
            for name, status in base.lumberjack_statuses.items()
            if name == "checks"
        },
        lumberjack_metrics={
            name: metrics
            for name, metrics in base.lumberjack_metrics.items()
            if name == "checks"
        },
        lumberjack_log_tails={
            name: tail
            for name, tail in base.lumberjack_log_tails.items()
            if name == "checks"
        },
        lumberjack_chop_names={
            name: chops
            for name, chops in base.lumberjack_chop_names.items()
            if name == "checks"
        },
        chop_snapshots={
            key: snap for key, snap in base.chop_snapshots.items() if key[0] == "checks"
        },
        lumberjack_snapshots={
            name: snap
            for name, snap in base.lumberjack_snapshots.items()
            if name == "checks"
        },
        routine_origins={
            name: origin
            for name, origin in base.routine_origins.items()
            if name == "checks"
        },
        chop_origins={
            key: origin
            for key, origin in base.chop_origins.items()
            if key[0] == "checks"
        },
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
        routine_origins={},
        chop_origins={},
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
