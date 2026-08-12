"""Deterministic AXE data builders shared by PNG snapshot tests."""

from __future__ import annotations

from typing import Any

from sase.ace.tui.actions.axe_display._data import (
    AxeCollectedData,
    BgCmdSnapshot,
    ChopRunSnapshot,
    ChopSnapshot,
    LumberjackSnapshot,
)
from sase.ace.tui.bgcmd import BackgroundCommandInfo
from sase.axe.chop_overrun import ChopOverrun
from sase.axe.state import ChopRunEntry, LumberjackMetrics, LumberjackStatus
from tests.ace.tui.visual._ace_png_snapshot_helpers import axe_collected_data


def axe_bgcmd_data() -> AxeCollectedData:
    info_a = BackgroundCommandInfo(
        command="just test --visual",
        project="visual_project",
        workspace_num=1,
        workspace_dir="/workspace/sase_1",
        started_at="2026-05-09T10:00:00",
        pid=12345,
    )
    info_b = BackgroundCommandInfo(
        command="just check",
        project="visual_project",
        workspace_num=2,
        workspace_dir="/workspace/sase_2",
        started_at="2026-05-09T10:05:00",
        pid=None,
        finished_at="2026-05-09T10:09:00",
    )
    slots = [(1, info_a), (2, info_b)]
    details = {
        1: BgCmdSnapshot(info=info_a, running=True, output_tail="running tests..."),
        2: BgCmdSnapshot(info=info_b, running=False, output_tail="check passed"),
    }
    return axe_collected_data(bgcmd_slots=slots, bgcmd_details=details)


def make_lumberjack_status(
    name: str, status: str = "running", chops: list[str] | None = None
) -> LumberjackStatus:
    return LumberjackStatus(
        name=name,
        pid=4242,
        started_at="2026-05-09T10:00:00",
        status=status,  # type: ignore[arg-type]
        interval=60,
        chops=list(chops or []),
        last_cycle="2026-05-09T10:05:00",
        cycles_run=12,
        errors_encountered=0,
        uptime_seconds=300,
    )


def make_chop_run(
    lumberjack: str,
    chop: str,
    *,
    run_id: str,
    status: str,
    output_tail: str | None = None,
    result: dict[str, Any] | None = None,
    proposals: list[dict[str, Any]] | None = None,
    launches: list[dict[str, Any]] | None = None,
    dry_run: bool = False,
    source: str = "scheduled",
    reason: str | None = None,
    error: str | None = None,
    traceback: str | None = None,
) -> ChopRunSnapshot:
    output_bytes = 64 if output_tail is None else len(output_tail.encode())
    tail = output_tail if output_tail is not None else f"{chop} {status} output\n"
    entry = ChopRunEntry(
        run_id=run_id,
        lumberjack_name=lumberjack,
        chop_name=chop,
        started_at="2026-05-09T10:00:00",
        finished_at="2026-05-09T10:00:01",
        duration_ms=1000,
        status=status,  # type: ignore[arg-type]
        exit_code=0 if status == "success" else 1,
        output_bytes=output_bytes,
        output_log=f"{run_id}.log",
        source=source,  # type: ignore[arg-type]
        result=result,
        proposals=list(proposals or []),
        launches=list(launches or []),
        dry_run=dry_run,
        reason=reason,
        error=error,
        traceback=traceback,
    )
    return ChopRunSnapshot(entry=entry, output_tail=tail)


def _single_chop_data(chop: ChopSnapshot) -> AxeCollectedData:
    """Build a one-lumberjack AXE snapshot focused on a single chop run."""
    status = make_lumberjack_status(chop.lumberjack_name, chops=[chop.chop_name])
    metrics = LumberjackMetrics(
        cycles_run=9, chops_executed=18, total_updates=9, errors_encountered=0
    )
    return axe_collected_data(
        lumberjack_names=[chop.lumberjack_name],
        lumberjack_statuses={chop.lumberjack_name: status},
        lumberjack_metrics={chop.lumberjack_name: metrics},
        lumberjack_log_tails={chop.lumberjack_name: ""},
        lumberjack_chop_names={chop.lumberjack_name: [chop.chop_name]},
        chop_snapshots={(chop.lumberjack_name, chop.chop_name): chop},
        lumberjack_snapshots={
            chop.lumberjack_name: LumberjackSnapshot(
                name=chop.lumberjack_name,
                description="Runs report-oriented chops for visual review",
                description_summary="Runs report-oriented chops for visual review",
                description_body="",
                status=status,
                metrics=metrics,
                log_tail="",
                chops=[chop],
            ),
        },
    )


def _rich_report_result() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "ok",
        "summary": "ci_watch: repos=4 green=1 red=1 pending=1 no_ci=1",
        "reason": "one repository still has a red CI streak",
        "counters": {"repos": 4, "green": 1, "red": 1, "pending": 1},
        "evidence": ["reports/ci_watch.decisions.json", "logs/ci_watch.log"],
        "report": {
            "title": "CI WATCH",
            "blocks": [
                {
                    "kind": "headline",
                    "text": "1 green · 1 red · 1 pending · 1 fix proposed",
                    "tone": "warn",
                },
                {"kind": "heading", "text": "REPOSITORIES"},
                {
                    "kind": "rows",
                    "columns": ["REPOSITORY", "STATE", "EVIDENCE"],
                    "rows": [
                        {
                            "cells": [
                                "sase-org/sase",
                                "red",
                                "unit · streak 2/2",
                            ],
                            "tone": "error",
                            "glyph": "▲",
                        },
                        {
                            "cells": ["sase-org/sase-core", "green", "a1b2c3d"],
                            "tone": "ok",
                            "glyph": "✓",
                        },
                        {
                            "cells": [
                                "sase-org/docs",
                                "pending",
                                "preview workflow queued",
                            ],
                            "tone": "warn",
                            "glyph": "◆",
                        },
                    ],
                },
                {
                    "kind": "kv",
                    "items": [
                        {"key": "mode", "value": "dry run", "tone": "warn"},
                        {"key": "agents", "value": "1 launched", "tone": "ok"},
                        {"key": "cap", "value": "1/3", "tone": "muted"},
                    ],
                },
                {
                    "kind": "gauge",
                    "label": "red streak",
                    "value": 2,
                    "max": 3,
                    "tone": "warn",
                },
                {"kind": "divider"},
                {
                    "kind": "text",
                    "text": "Fix proposal is ready for review.",
                    "tone": "info",
                },
            ],
        },
    }


def axe_chop_report_rich_120x40() -> AxeCollectedData:
    """Report-rich chop run exercising every rendered AXE report section."""
    run = make_chop_run(
        "reports",
        "ci_watch",
        run_id="20260729T100000_000000",
        status="success",
        output_tail=(
            "ci_watch: scanned 4 repositories\n"
            "ci_watch: proposed ci_fix.sase for sase-org/sase\n"
        ),
        result=_rich_report_result(),
        launches=[{"agent_name": "ci_fix.sase", "clan": "ci_fix"}],
        proposals=[{"agent_name": "ci_fix.sase", "outcome": "accepted"}],
        dry_run=True,
    )
    chop = ChopSnapshot(
        lumberjack_name="reports",
        chop_name="ci_watch",
        description="Watch configured repository CI and propose fixes",
        description_summary="Watch configured repository CI and propose fixes",
        description_body="",
        runs=[run],
        script="bugyi_chop_ci_watch",
    )
    return _single_chop_data(chop)


def axe_chop_report_absent_120x40() -> AxeCollectedData:
    """Successful chop run with RESULT card data but no authored report."""
    result = {
        "schema_version": 1,
        "status": "ok",
        "summary": "builtin cleanup completed",
        "counters": {"cleaned": 6, "kept": 2},
        "evidence": ["reports/cleanup.json"],
    }
    run = make_chop_run(
        "reports",
        "cleanup",
        run_id="20260729T101500_000000",
        status="success",
        output_tail="cleanup: removed 6 stale entries\ncleanup: kept 2 active entries\n",
        result=result,
        launches=[{"agent_name": "cleanup.sase", "clan": "maintenance"}],
    )
    chop = ChopSnapshot(
        lumberjack_name="reports",
        chop_name="cleanup",
        description="Builtin maintenance chop without an authored report",
        description_summary="Builtin maintenance chop without an authored report",
        description_body="",
        runs=[run],
        script="sase_chop_cleanup",
    )
    return _single_chop_data(chop)


def axe_chop_report_error_120x40() -> AxeCollectedData:
    """check_error run whose reason and error surface in the RESULT card."""
    result = {
        "schema_version": 1,
        "status": "check_error",
        "summary": "recent_bug_audit result validation failed",
        "reason": "the chop wrote a malformed result document",
        "counters": {"checked": 1, "failed": 1},
    }
    run = make_chop_run(
        "reports",
        "recent_bug_audit",
        run_id="20260729T103000_000000",
        status="check_error",
        output_tail="",
        result=result,
        reason="the chop wrote a malformed result document",
        error="invalid chop result: $.report.blocks[0].text contains a newline",
    )
    chop = ChopSnapshot(
        lumberjack_name="reports",
        chop_name="recent_bug_audit",
        description="Audit recent work for user-visible bug regressions",
        description_summary="Audit recent work for user-visible bug regressions",
        description_body="",
        runs=[run],
        script="bugyi_chop_recent_bug_audit",
    )
    return _single_chop_data(chop)


def axe_chop_report_narrow_70x36() -> AxeCollectedData:
    """The rich report in a narrow terminal, proving stacked rows and kv pairs."""
    result = {
        "schema_version": 1,
        "status": "ok",
        "summary": "ci_watch: narrow report",
        "counters": {"red": 1},
        "report": _rich_report_result()["report"],
    }
    run = make_chop_run(
        "reports",
        "ci_watch",
        run_id="20260729T100000_000000",
        status="success",
        output_tail="ci_watch: proposed ci_fix.sase\n",
        result=result,
    )
    chop = ChopSnapshot(
        lumberjack_name="reports",
        chop_name="ci_watch",
        description="Watch configured repository CI and propose fixes",
        description_summary="Watch configured repository CI and propose fixes",
        description_body="",
        runs=[run],
        script="bugyi_chop_ci_watch",
    )
    return _single_chop_data(chop)


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
        started_at="2026-05-09T10:05:00",
        pid=12345,
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


def axe_lumberjack_error_data() -> AxeCollectedData:
    """Build a single lumberjack in an error state with one failed run."""
    failed_chop = ChopSnapshot(
        lumberjack_name="hooks",
        chop_name="fast_lint",
        description="fast lint",
        runs=[
            make_chop_run(
                "hooks",
                "fast_lint",
                run_id="20260509T100000_000000",
                status="failure",
            ),
        ],
    )
    error_status = LumberjackStatus(
        name="hooks",
        pid=4242,
        started_at="2026-05-09T10:00:00",
        status="error",
        interval=60,
        chops=["fast_lint"],
        last_cycle="2026-05-09T10:05:00",
        cycles_run=5,
        errors_encountered=3,
        uptime_seconds=300,
    )
    metrics = LumberjackMetrics(
        cycles_run=5, chops_executed=5, total_updates=2, errors_encountered=3
    )
    log_tail = "ERROR: hooks crashed at cycle 5"
    return axe_collected_data(
        lumberjack_names=["hooks"],
        lumberjack_statuses={"hooks": error_status},
        lumberjack_metrics={"hooks": metrics},
        lumberjack_log_tails={"hooks": log_tail},
        lumberjack_chop_names={"hooks": ["fast_lint"]},
        chop_snapshots={("hooks", "fast_lint"): failed_chop},
        lumberjack_snapshots={
            "hooks": LumberjackSnapshot(
                name="hooks",
                status=error_status,
                metrics=metrics,
                log_tail=log_tail,
                chops=[failed_chop],
            ),
        },
    )


def axe_running_chop_data() -> AxeCollectedData:
    """Build an in-flight manual chop run streaming its output."""
    # Naive ISO timestamps make _format_relative_time / _format_runtime
    # return the deterministic "unknown" fallback (they require tz-aware
    # input), so the rendered "Elapsed"/"When" cells stay stable across runs.
    live_entry = ChopRunEntry(
        run_id="20260509T100200_000000",
        lumberjack_name="hooks",
        chop_name="slow_typecheck",
        started_at="2026-05-09T10:02:00",
        finished_at=None,
        duration_ms=0,
        status="running",  # type: ignore[arg-type]
        exit_code=None,
        pid=98765,
        output_bytes=42,
        output_log="20260509T100200_000000.log",
        source="manual",  # type: ignore[arg-type]
    )
    live_run = ChopRunSnapshot(
        entry=live_entry,
        output_tail="checking module foo...\nchecking module bar...\n",
    )
    hooks_slow = ChopSnapshot(
        lumberjack_name="hooks",
        chop_name="slow_typecheck",
        description="slow typecheck",
        runs=[live_run],
    )
    chop_snapshots = {("hooks", "slow_typecheck"): hooks_slow}
    hooks_status = make_lumberjack_status("hooks", chops=["slow_typecheck"])
    metrics = LumberjackMetrics(
        cycles_run=12, chops_executed=24, total_updates=12, errors_encountered=0
    )
    lumberjack_snapshots = {
        "hooks": LumberjackSnapshot(
            name="hooks",
            status=hooks_status,
            metrics=metrics,
            log_tail="",
            chops=[hooks_slow],
        ),
    }
    return axe_collected_data(
        lumberjack_names=["hooks"],
        lumberjack_statuses={"hooks": hooks_status},
        lumberjack_metrics={"hooks": metrics},
        lumberjack_log_tails={"hooks": ""},
        lumberjack_chop_names={"hooks": ["slow_typecheck"]},
        chop_snapshots=chop_snapshots,
        lumberjack_snapshots=lumberjack_snapshots,
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
        started_at="2026-05-09T10:05:00",
        pid=12345,
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


def axe_chop_overrun_data() -> AxeCollectedData:
    """One lumberjack with an over chop, an intermittent chop, and a healthy one.

    Pins the sidebar chop chips (bold amber ``over``, dim amber
    ``intermittent``, none for the healthy chop), the lumberjack roll-up
    chip, the overview table's PACE column, and the advisory line below it —
    every surface the tab_indicator phase touches, in one screenshot.
    """
    over_chop = ChopSnapshot(
        lumberjack_name="hooks",
        chop_name="mentor_sweep",
        description="Sweep open mentor threads for stale review requests",
        runs=[
            make_chop_run(
                "hooks",
                "mentor_sweep",
                run_id="20260509T100400_000000",
                status="success",
            ),
        ],
        interval_seconds=60,
        interval_source="runtime",
        overrun=ChopOverrun(
            level="over",
            sampled_runs=5,
            over_runs=3,
            worst_ratio=4.0,
            worst_blocking_ms=240_000,
            latest_ratio=4.0,
        ),
    )
    intermittent_chop = ChopSnapshot(
        lumberjack_name="hooks",
        chop_name="bead_triage",
        description="Triage newly opened task beads",
        runs=[
            make_chop_run(
                "hooks",
                "bead_triage",
                run_id="20260509T100300_000000",
                status="success",
            ),
        ],
        interval_seconds=60,
        interval_source="runtime",
        overrun=ChopOverrun(
            level="intermittent",
            sampled_runs=8,
            over_runs=2,
            worst_ratio=1.2,
            worst_blocking_ms=72_000,
            latest_ratio=0.4,
        ),
    )
    healthy_chop = ChopSnapshot(
        lumberjack_name="hooks",
        chop_name="fix_hooks",
        description="Apply automatic hook fixes",
        runs=[
            make_chop_run(
                "hooks",
                "fix_hooks",
                run_id="20260509T100200_000000",
                status="success",
            ),
        ],
        interval_seconds=60,
        interval_source="runtime",
        overrun=ChopOverrun(
            level="none",
            sampled_runs=6,
            over_runs=0,
            worst_ratio=0.1,
            worst_blocking_ms=3_100,
            latest_ratio=0.1,
        ),
    )
    chop_snapshots = {
        ("hooks", "mentor_sweep"): over_chop,
        ("hooks", "bead_triage"): intermittent_chop,
        ("hooks", "fix_hooks"): healthy_chop,
    }
    hooks_status = make_lumberjack_status(
        "hooks", chops=["fix_hooks", "bead_triage", "mentor_sweep"]
    )
    metrics = LumberjackMetrics(
        cycles_run=31, chops_executed=93, total_updates=31, errors_encountered=0
    )
    return axe_collected_data(
        lumberjack_names=["hooks"],
        lumberjack_statuses={"hooks": hooks_status},
        lumberjack_metrics={"hooks": metrics},
        lumberjack_log_tails={"hooks": ""},
        lumberjack_chop_names={"hooks": ["fix_hooks", "bead_triage", "mentor_sweep"]},
        chop_snapshots=chop_snapshots,
        lumberjack_snapshots={
            "hooks": LumberjackSnapshot(
                name="hooks",
                status=hooks_status,
                metrics=metrics,
                log_tail="",
                chops=[healthy_chop, intermittent_chop, over_chop],
                overrun_chop_count=1,
                intermittent_chop_count=1,
            ),
        },
    )
