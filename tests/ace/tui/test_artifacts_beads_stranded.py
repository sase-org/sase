"""Stranded badges, leaf counts, details, and deferred refresh lifecycle."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from threading import get_ident
from unittest.mock import Mock

import pytest
from rich.console import Console

from sase.ace.tui.models import agent_stranded
from sase.ace.tui.widgets.artifacts.beads_detail import bead_properties_header
from sase.ace.tui.widgets.artifacts.beads_list import build_bead_options
from sase.ace.tui.widgets.artifacts.beads_pane import ArtifactsBeadsPane
from sase.ace.tui.widgets.artifacts.beads_rendering import build_beads_status
from sase.ace.tui.widgets.artifacts import beads_stranded_refresh as refresh
from sase.ace.tui.widgets.artifacts.beads_stranded import epic_stranded_style
from sase.bead.model import Status
from sase.bead.stranded_presentation import (
    STRANDED_BREADCRUMB_STYLE,
    STRANDED_LEAF_STYLE,
)
from tests.ace.tui._artifacts_beads_stranded_helpers import stranded_snapshot


def test_stranded_rows_count_tasks_and_style_ancestors(tmp_path: Path, monkeypatch):
    value, _ = stranded_snapshot(tmp_path, monkeypatch)
    options, _ = build_bead_options(
        value,
        project_scope="alpha",
        loading=False,
        expanded_epics={("alpha", "alpha-1")},
    )
    rows = {option.id: option.prompt for option in options}
    assert "in progress ⚐ 1h" in rows["phase:alpha-1.2"].plain
    assert "in progress ⚐" in rows["phase:alpha-1.1"].plain
    assert "in progress ⚐ 2h" in rows["task:alpha-open"].plain
    assert "⚐" not in rows["task:alpha-ready"].plain
    assert "⚐ stranded" in rows["header:epics"].plain
    assert "⚐" in rows["epic:alpha-1"].plain
    assert "►" not in rows["epic:alpha-1"].plain
    assert epic_stranded_style("alpha", "alpha-1") == STRANDED_LEAF_STYLE
    status = build_beads_status(value, loading=False, load_error=None).plain
    assert "⚐ 2 stranded" in status
    # All-project mode counts each project once, never its ancestor breadcrumbs.
    status = build_beads_status(
        replace(value, project=None), loading=False, load_error=None
    ).plain
    assert "⚐ 2 stranded" in status
    agent_stranded._STRANDED_REPORT_CACHE.clear()
    assert (
        "stranded"
        not in build_beads_status(value, loading=False, load_error=None).plain
    )


def test_open_unassigned_recovered_task_keeps_stranded_flag(
    tmp_path: Path, monkeypatch
) -> None:
    value, _ = stranded_snapshot(tmp_path, monkeypatch)
    task = next(item for item in value.tasks if item.issue.id == "alpha-open")
    task.issue.status = Status.OPEN
    task.issue.assignee = ""
    options, _ = build_bead_options(
        value,
        project_scope="alpha",
        loading=False,
        expanded_epics={("alpha", "alpha-1")},
    )
    rows = {option.id: option.prompt for option in options}
    assert "⚐" in rows["task:alpha-open"].plain
    assert "open" in rows["task:alpha-open"].plain.lower()


@pytest.mark.parametrize("direct", [False, True])
def test_epic_breadcrumb_for_deep_leaf_and_bold_for_stranded_epic(
    tmp_path, monkeypatch, direct
):
    _, report = stranded_snapshot(tmp_path, monkeypatch)
    verdicts = list(report.report.verdicts)
    verdicts[2] = replace(verdicts[2], parent_id="alpha-1.1.child")
    if direct:
        verdicts[0] = replace(verdicts[0], state="stranded")
    report = replace(report, report=replace(report.report, verdicts=tuple(verdicts)))
    agent_stranded._STRANDED_REPORT_CACHE.set("alpha", report, "fixture")
    assert epic_stranded_style("alpha", "alpha-1") == (
        STRANDED_LEAF_STYLE if direct else STRANDED_BREADCRUMB_STYLE
    )


def test_stranded_detail_shows_cause_and_blocking_leaf(tmp_path, monkeypatch):
    value, _ = stranded_snapshot(tmp_path, monkeypatch)
    console = Console(width=160, color_system=None)
    for phase, expected in zip(
        value.phases_by_epic["alpha", "alpha-1"],
        (
            "Blocked by stranded alpha-1.2",
            "alpha-1.2--3 · ended with bead_action keep; nothing resumes it · 1h",
        ),
        strict=True,
    ):
        with console.capture() as capture:
            console.print(
                bead_properties_header(
                    phase.issue, value, project="alpha", project_name="Alpha"
                )
            )
        assert expected in capture.get()
        assert "Stranded" in capture.get()


async def test_deferred_warmup_off_thread_and_unchanged_report_skips_render(
    tmp_path, monkeypatch
):
    value, _ = stranded_snapshot(tmp_path, monkeypatch)
    pane = ArtifactsBeadsPane()
    pane.project_scope = "alpha"
    pane._snapshot = value
    pane._artifacts_active = True
    rendered = Mock()
    monkeypatch.setattr(pane, "_refresh_options", rendered)
    threads = []
    monkeypatch.setattr(
        refresh,
        "warm_stranded_work_reports",
        lambda *args, **kw: threads.append(get_ident()),
    )
    pane._schedule_stranded_refresh()
    assert not threads and not rendered.called
    await asyncio.gather(*pane._beads_stranded_refresh_tasks)
    assert threads and threads[0] != get_ident()
    rendered.assert_called_once_with()
    pane._schedule_stranded_refresh()
    await asyncio.gather(*pane._beads_stranded_refresh_tasks)
    rendered.assert_called_once_with()
    agent_stranded._STRANDED_REPORT_CACHE.clear()
    pane._schedule_stranded_refresh()
    await asyncio.gather(*pane._beads_stranded_refresh_tasks)
    assert rendered.call_count == 2


async def test_warmup_coalesces_and_rejects_old_scope(tmp_path, monkeypatch):
    value, _ = stranded_snapshot(tmp_path, monkeypatch)
    pane = ArtifactsBeadsPane()
    pane.project_scope = "alpha"
    pane._snapshot = value
    pane._artifacts_active = True
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow_thread(*args, **kwargs):
        entered.set()
        await release.wait()

    monkeypatch.setattr(refresh.asyncio, "to_thread", slow_thread)
    rendered = Mock()
    monkeypatch.setattr(pane, "_refresh_options", rendered)
    pane._schedule_stranded_refresh()
    await entered.wait()
    pane._schedule_stranded_refresh()
    assert len(pane._beads_stranded_refresh_tasks) == 1
    pane.project_scope = "beta"
    release.set()
    await asyncio.gather(*pane._beads_stranded_refresh_tasks)
    rendered.assert_not_called()
    assert not pane._stranded_running
