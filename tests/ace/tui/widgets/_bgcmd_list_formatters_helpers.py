"""Shared builders and widget host for bgcmd-list row-formatter tests.

Pinned by the AXE-tab visual redesign plan (sdd/plans/202605/
axe_tab_visual_redesign.md). The three row taxonomies (lumberjack,
chop, bgcmd) must be visually distinguishable at a glance:

* lumberjack rows carry a strong top-level accent in the gold hue;
* chop rows render with a tree-style connector and a subordinate
  dim-gold/copper colour;
* bgcmd (oneshot) rows lead with a state glyph (``▷`` running, ``✓``
  exit 0, ``✗`` failed) and a muted slot badge, and end with a chip that
  carries the recorded exit code, so background commands cannot be
  mistaken for AXE-managed lumberjack rows;
* when both AXE-managed and bgcmd rows are present, the first bgcmd
  row carries a leading ``── oneshots ──`` divider line that separates
  the oneshot section from the service/lumberjack tree above.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets.option_list import Option

from sase.ace.tui.actions.axe_display._data import ChopSnapshot
from sase.ace.tui.bgcmd import BackgroundCommandInfo
from sase.ace.tui.widgets.bgcmd_list import BgCmdList
from sase.axe.chop_overrun import ChopOverrun
from sase.axe.state import LumberjackStatus


def _bg_info(command: str) -> BackgroundCommandInfo:
    return BackgroundCommandInfo(
        command=command,
        project="proj",
        workspace_num=0,
        workspace_dir="/tmp",
        started_at="2026-05-11T00:00:00",
    )


def _make_status(name: str, status: str = "running") -> LumberjackStatus:
    return LumberjackStatus(
        name=name,
        pid=4242,
        started_at="2026-05-09T10:00:00",
        status=status,  # type: ignore[arg-type]
        interval=60,
        chops=[],
        last_cycle="2026-05-09T10:05:00",
        cycles_run=7,
        errors_encountered=0,
        uptime_seconds=300,
    )


class _Host(App):
    def compose(self) -> ComposeResult:
        yield BgCmdList(id="bgcmd-list")


def _overrun(
    level: str, *, worst_ratio: float | None = 2.4, latest_ratio: float | None = 2.4
) -> ChopOverrun:
    return ChopOverrun(
        level=level,  # type: ignore[arg-type]
        sampled_runs=5,
        over_runs=1 if level != "none" else 0,
        worst_ratio=worst_ratio,
        worst_blocking_ms=None,
        latest_ratio=latest_ratio,
        run_ratios=(latest_ratio,),
    )


def _chop_snapshot(
    *, enabled: bool = True, overrun: ChopOverrun | None = None
) -> ChopSnapshot:
    return ChopSnapshot(
        lumberjack_name="hooks",
        chop_name="fast_lint",
        description="",
        runs=[],
        enabled=enabled,
        overrun=overrun,
    )


def _option_text(option: Option) -> Text:
    assert isinstance(option.prompt, Text)
    return option.prompt


def _styles_in(text: Text) -> set[str]:
    return {str(span.style) for span in text.spans}
