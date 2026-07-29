"""XPrompts-view renderers for the Admin Center Statistics pane."""

from __future__ import annotations

from typing import Any

from rich import box
from rich.align import Align
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.telemetry.render import categorical_color, format_duration

from .statistics_pane_data import StatisticsViewData, XPromptsGroupBy
from .statistics_pane_projects import StatisticsProjectsRenderingMixin

_ACCENT = "#FF87D7"
_CYAN = "#87D7FF"
_GOLD = "#FFD700"
_GREEN = "#5FD75F"


class StatisticsXPromptsRenderingMixin:
    """Render launch-boundary xprompt usage without performing any I/O."""

    _xprompts_group_by: XPromptsGroupBy
    _project_filter: str | None
    size: Any

    @staticmethod
    def _percent(value: float) -> str:
        raise NotImplementedError

    @staticmethod
    def _share_bar(value: float, maximum: float, *, width: int = 14) -> Text:
        raise NotImplementedError

    def _effective_key(self, action: str) -> str:
        raise NotImplementedError

    def _effective_project_keys(self) -> str:
        raise NotImplementedError

    def _xprompts_renderable(self, result: StatisticsViewData) -> Any:
        xprompts = result.views.xprompts
        if not xprompts.available:
            return self._xprompts_unavailable_renderable()
        if xprompts.runs_with_xprompts == 0:
            return self._xprompts_empty_renderable(result)

        if self._xprompts_group_by == "model":
            body = self._xprompts_drilldown_renderable(
                xprompts,
                dimension="model",
            )
        elif self._xprompts_group_by == "project":
            body = self._xprompts_drilldown_renderable(
                xprompts,
                dimension="project",
            )
        elif self._xprompts_group_by == "pairing":
            body = self._xprompts_drilldown_renderable(
                xprompts,
                dimension="pairing",
            )
        else:
            body = self._xprompts_usage_renderable(xprompts)
        return Group(
            body,
            StatisticsProjectsRenderingMixin._legend_note("xprompts"),
        )

    def _xprompts_usage_renderable(self, xprompts: Any) -> Group:
        table = Table(box=box.SIMPLE, expand=True)
        table.add_column("XPrompt", ratio=1, min_width=14)
        table.add_column("Runs", justify="right", style=_CYAN)
        table.add_column("Refs", justify="right")
        table.add_column("Share", justify="right")
        table.add_column("Scale")
        table.add_column("Agents", justify="right")
        table.add_column("Success", justify="right", style=_GREEN)
        table.add_column("Wall", justify="right")
        table.add_column("Last used", justify="right")
        for row in xprompts.rows:
            table.add_row(
                self._xprompt_cell(row),
                str(row.runs),
                str(row.references),
                self._percent(row.share),
                self._share_bar(row.share, 1.0, width=10),
                str(row.distinct_agents),
                self._percent(row.success_rate),
                format_duration(row.total_runtime_seconds),
                StatisticsProjectsRenderingMixin._format_timestamp(row.last_run_ts),
            )
        return Group(
            self._xprompts_summary(xprompts),
            Panel(table, title="By Usage", border_style=_ACCENT),
        )

    def _xprompts_drilldown_renderable(
        self,
        xprompts: Any,
        *,
        dimension: XPromptsGroupBy,
    ) -> Group:
        headings = {
            "model": ("XPrompt → Model", "By Model"),
            "project": ("XPrompt → Project", "By Project"),
            "pairing": ("XPrompt → Used with", "Used With"),
        }
        column_label, title = headings[dimension]
        table = Table(box=box.SIMPLE, expand=True)
        table.add_column(column_label, ratio=1, min_width=18)
        table.add_column("Runs", justify="right", style=_CYAN)
        table.add_column("Share", justify="right")
        table.add_column("Scale")
        for row in xprompts.rows:
            table.add_row(
                self._xprompt_cell(row),
                str(row.runs),
                self._percent(row.share),
                self._share_bar(row.share, 1.0, width=10),
                style="bold",
            )
            children = getattr(
                row,
                {
                    "model": "models",
                    "project": "projects",
                    "pairing": "partners",
                }[dimension],
            )
            if not children:
                empty_label = {
                    "model": "(no model recorded)",
                    "project": "(no project recorded)",
                    "pairing": "(used alone)",
                }[dimension]
                table.add_row(
                    Text(f"  {empty_label}", style="dim italic"),
                    Text("—", style="dim"),
                    Text("—", style="dim"),
                    Text("—", style="dim"),
                    style="dim",
                )
                continue
            for child in children:
                if dimension == "project":
                    label = Text("  ")
                    label.append_text(
                        StatisticsProjectsRenderingMixin._project_cell(
                            child.key,
                            child.label,
                        )
                    )
                elif dimension == "pairing":
                    label = self._partner_cell(child.label)
                else:
                    label = Text(f"  {child.label}")
                table.add_row(
                    label,
                    str(child.count),
                    self._percent(child.share),
                    self._share_bar(child.share, 1.0, width=10),
                )
        return Group(
            self._xprompts_summary(xprompts),
            Panel(table, title=title, border_style=_ACCENT),
        )

    @staticmethod
    def _xprompt_cell(row: Any) -> Text:
        text = Text(no_wrap=True, overflow="ellipsis")
        text.append(f"#{row.name}", style=f"bold {categorical_color(row.name)}")
        kind = {"workflow": "wf", "part": "part"}.get(row.kind, row.kind)
        if kind:
            text.append(f"  {kind}", style="dim")
        if row.tags:
            text.append(f"  {', '.join(row.tags)}", style="dim italic")
        return text

    @staticmethod
    def _partner_cell(name: str) -> Text:
        text = Text("  ")
        text.append(f"#{name}", style=categorical_color(name))
        return text

    def _xprompts_summary(self, xprompts: Any) -> Text:
        total_runs = xprompts.runs_with_xprompts + xprompts.runs_without_xprompts
        without_share = (
            xprompts.runs_without_xprompts / total_runs if total_runs else 0.0
        )
        summary = Text(
            f"{xprompts.distinct_xprompts} xprompts · "
            f"{xprompts.runs_with_xprompts} runs referenced · "
            f"{xprompts.total_references} references · "
            f"{xprompts.runs_without_xprompts} runs without xprompts "
            f"({self._percent(without_share)})",
            style="dim",
        )
        if xprompts.truncated_rows:
            summary.append(
                f" · {xprompts.truncated_rows} more xprompts not shown.",
                style="dim italic",
            )
        return summary

    def _xprompts_unavailable_renderable(self) -> Panel:
        refresh_key = self._effective_key("refresh")
        retry = Text()
        retry.append(f"Press {refresh_key}", style=f"bold {_ACCENT}")
        retry.append(" to refresh after updating the installed sase-core-rs build.")
        return Panel(
            Align.center(
                Group(
                    Text(
                        "The installed sase-core-rs build does not report "
                        "xprompt usage yet.",
                        style="dim italic",
                    ),
                    retry,
                ),
                vertical="middle",
            ),
            title="XPrompt statistics unavailable",
            border_style="#444444",
            height=max(8, int(self.size.height or 24) - 11),
        )

    def _xprompts_empty_renderable(self, result: StatisticsViewData) -> Panel:
        range_key = self._effective_key("cycle_range")
        recovery = Text()
        recovery.append(f"Press {range_key}", style=f"bold {_CYAN}")
        recovery.append(" to widen the range.")
        lines = [
            Text(
                "No prompt in "
                f"{result.selected_range.display_label} referenced an xprompt.",
                style="dim italic",
            ),
            recovery,
        ]
        if result.project_filter is not None:
            project_keys = self._effective_project_keys()
            project_label = result.project_display_snapshot.label_for(
                result.project_filter
            )
            clear_filter = Text()
            clear_filter.append(f"Press {project_keys}", style=f"bold {_GOLD}")
            clear_filter.append(f" to clear the {project_label} project filter.")
            lines.append(clear_filter)
        return Panel(
            Align.center(Group(*lines), vertical="middle"),
            title="XPrompts",
            border_style="#444444",
            height=max(8, int(self.size.height or 24) - 11),
        )


__all__ = ["StatisticsXPromptsRenderingMixin"]
