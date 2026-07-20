"""Projects-view renderers for the Admin Center Statistics pane."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.ace.tui.changespec_status import changespec_status_glyph
from sase.telemetry.render import categorical_color, format_duration

from .statistics_pane_data import ProjectsGroupBy, StatisticsView
from .statistics_pane_legends import VIEW_LEGENDS

_ACCENT = "#FF87D7"
_CYAN = "#87D7FF"
_GREEN = "#5FD75F"
_RED = "#FF5F5F"


class StatisticsProjectsRenderingMixin:
    """Render the three Projects grouping strategies without performing I/O."""

    _projects_group_by: ProjectsGroupBy

    @staticmethod
    def _percent(value: float) -> str:
        raise NotImplementedError

    @staticmethod
    def _share_bar(value: float, maximum: float, *, width: int = 14) -> Text:
        raise NotImplementedError

    @staticmethod
    def _legend_note(view: StatisticsView) -> Text:
        """Render one dim, newline-free metric definition line for ``view``."""
        note = Text(style="dim")
        for index, entry in enumerate(VIEW_LEGENDS[view]):
            if index:
                note.append("  ·  ")
            note.append(entry.term, style="bold dim")
            note.append(f" = {entry.meaning}")
        return note

    def _projects_renderable(self, projects: Any) -> Group:
        if self._projects_group_by == "changespec":
            renderable = self._projects_by_changespec_renderable(projects)
        elif self._projects_group_by == "drilldown":
            renderable = self._projects_drilldown_renderable(projects)
        else:
            renderable = self._projects_by_project_renderable(projects)
        return Group(renderable, self._legend_note("projects"))

    def _projects_by_project_renderable(self, projects: Any) -> Group:
        table = Table(box=box.SIMPLE, expand=True)
        table.add_column("Project", style="bold", ratio=1, min_width=14)
        table.add_column("Runs", justify="right")
        table.add_column("Success", justify="right", style=_GREEN)
        table.add_column("Commits", justify="right", style=_CYAN)
        table.add_column("Specs", justify="right")
        table.add_column("Wall", justify="right")
        table.add_column("Share", justify="right")
        table.add_column("Last", justify="right")
        total_runs = sum(row.runs for row in projects.projects)
        for row in sorted(
            projects.projects,
            key=lambda item: (
                -item.runs,
                item.project_label.casefold(),
                item.project_key,
            ),
        ):
            table.add_row(
                self._project_cell(row.project_key, row.project_label),
                self._project_runs_cell(row),
                self._percent(row.success_rate),
                str(row.commits),
                str(row.distinct_changespecs),
                format_duration(row.total_runtime_seconds),
                self._share_bar(row.runs, total_runs, width=10),
                self._format_timestamp(row.last_run_ts),
            )
        return Group(
            self._projects_summary(projects),
            Panel(table, title="By Project", border_style=_ACCENT),
            *self._projects_footnotes(projects),
        )

    def _projects_by_changespec_renderable(self, projects: Any) -> Group:
        table = Table(box=box.SIMPLE, expand=True)
        table.add_column("ChangeSpec", style="bold", ratio=1)
        table.add_column("Project", ratio=1)
        table.add_column("Runs", justify="right", style=_CYAN)
        table.add_column("Agents", justify="right")
        table.add_column("Commits", justify="right")
        table.add_column("Wall time", justify="right")
        table.add_column("Last run", justify="right")
        rows = sorted(
            projects.changespecs,
            key=lambda item: (
                -item.runs,
                item.project_label.casefold(),
                item.project_key,
                item.changespec_label.casefold(),
                item.changespec_key,
            ),
        )
        for row in rows:
            table.add_row(
                self._changespec_cell(row),
                self._project_cell(
                    row.project_key,
                    row.project_label,
                    bold=False,
                ),
                str(row.runs),
                str(row.distinct_agents),
                str(row.commits),
                format_duration(row.total_runtime_seconds),
                self._format_timestamp(row.last_run_ts),
            )
        table.add_row(
            Text("(no ChangeSpec)", style="dim italic"),
            Text("all projects", style="dim"),
            Text(str(projects.unattributed_runs), style="dim"),
            Text("—", style="dim"),
            Text("—", style="dim"),
            Text("—", style="dim"),
            Text("—", style="dim"),
            style="dim",
        )
        notes: list[Text] = []
        if not rows:
            notes.append(
                Text(
                    "No attributed ChangeSpecs in this range; runs are shown in "
                    "the (no ChangeSpec) row.",
                    style="dim italic",
                )
            )
        notes.extend(self._projects_footnotes(projects))
        return Group(
            self._projects_summary(projects),
            Panel(table, title="By ChangeSpec", border_style=_ACCENT),
            *notes,
        )

    def _projects_drilldown_renderable(self, projects: Any) -> Group:
        table = Table(box=box.SIMPLE, expand=True)
        table.add_column("Project → ChangeSpec", ratio=1)
        table.add_column("Runs", justify="right")
        table.add_column("Agents", justify="right")
        table.add_column("Commits", justify="right")
        table.add_column("Wall time", justify="right")
        table.add_column("Last run", justify="right")
        for project in sorted(
            projects.projects,
            key=lambda item: (
                -item.runs,
                item.project_label.casefold(),
                item.project_key,
            ),
        ):
            table.add_row(
                self._project_cell(project.project_key, project.project_label),
                self._project_runs_cell(project),
                "—",
                str(project.commits),
                format_duration(project.total_runtime_seconds),
                self._format_timestamp(project.last_run_ts),
                style="bold",
            )
            for changespec in sorted(
                project.changespecs,
                key=lambda item: (
                    -item.runs,
                    item.changespec_label.casefold(),
                    item.changespec_key,
                ),
            ):
                table.add_row(
                    self._changespec_cell(changespec, indent=True),
                    str(changespec.runs),
                    str(changespec.distinct_agents),
                    str(changespec.commits),
                    format_duration(changespec.total_runtime_seconds),
                    self._format_timestamp(changespec.last_run_ts),
                )
            table.add_row(
                Text("  (no ChangeSpec)", style="dim italic"),
                Text(str(project.unattributed_runs), style="dim"),
                Text("—", style="dim"),
                Text("—", style="dim"),
                Text("—", style="dim"),
                Text("—", style="dim"),
                style="dim",
            )
        return Group(
            self._projects_summary(projects),
            Panel(table, title="Project → ChangeSpec", border_style=_ACCENT),
            *self._projects_footnotes(projects),
        )

    @staticmethod
    def _projects_summary(projects: Any) -> Text:
        return Text(
            f"{projects.project_count} projects · "
            f"{projects.changespec_count} ChangeSpecs · "
            f"{projects.unattributed_runs} unattributed runs",
            style="dim",
        )

    @staticmethod
    def _projects_footnotes(projects: Any) -> tuple[Text, ...]:
        notes: list[Text] = []
        if projects.truncated_changespec_rows:
            notes.append(
                Text(
                    f"{projects.truncated_changespec_rows} additional ChangeSpec "
                    "rows not shown.",
                    style="dim italic",
                )
            )
        if projects.malformed_spec_files_skipped:
            notes.append(
                Text(
                    f"{projects.malformed_spec_files_skipped} malformed ChangeSpec "
                    "files skipped.",
                    style="dim italic",
                )
            )
        return tuple(notes)

    @staticmethod
    def _project_cell(
        project_key: str,
        project_label: str,
        *,
        bold: bool = True,
    ) -> Text:
        text = Text(no_wrap=True, overflow="ellipsis")
        text.append("■ ", style=categorical_color(project_key))
        text.append(project_label, style="bold" if bold else None)
        return text

    @staticmethod
    def _project_runs_cell(project: Any) -> Text:
        text = Text(str(project.runs), style=f"bold {_CYAN}")
        text.append(f"  ✓ {project.completed}", style=_GREEN)
        text.append(f"  × {project.failed}", style=_RED)
        return text

    @staticmethod
    def _changespec_cell(changespec: Any, *, indent: bool = False) -> Text:
        text = Text("  " if indent else "")
        glyph, color = changespec_status_glyph(changespec.status)
        text.append(f"{glyph} ", style=f"bold {color}")
        text.append(changespec.changespec_label, style="bold")
        if changespec.has_pr:
            text.append(" ↗", style="dim")
        return text

    @staticmethod
    def _format_timestamp(timestamp: float) -> str:
        if timestamp <= 0:
            return "—"
        return datetime.fromtimestamp(timestamp).astimezone().strftime("%b %d %H:%M")


__all__ = ["StatisticsProjectsRenderingMixin"]
