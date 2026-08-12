"""Report-card data builders for AXE PNG snapshot tests."""

from __future__ import annotations

from typing import Any

from sase.ace.tui.actions.axe_display._data import AxeCollectedData, ChopSnapshot
from tests.ace.tui.visual._ace_axe_png_snapshot_builders import (
    make_chop_run,
    single_chop_data,
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
    return single_chop_data(chop)


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
    return single_chop_data(chop)


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
    return single_chop_data(chop)


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
    return single_chop_data(chop)
