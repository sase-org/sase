"""Rich renderables for the Admin Center Statistics pane views."""

from __future__ import annotations

from typing import Any

from rich import box
from rich.columns import Columns
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from sase.telemetry.render import format_duration

from .statistics_pane_data import StatisticsView, StatisticsViewData
from .statistics_pane_projects import StatisticsProjectsRenderingMixin

_ACCENT = "#FF87D7"
_CYAN = "#87D7FF"
_GOLD = "#FFD700"
_GREEN = "#5FD75F"
_RED = "#FF5F5F"


class StatisticsViewsRenderingMixin(StatisticsProjectsRenderingMixin):
    """Build view-specific Rich renderables without performing any I/O."""

    _view: StatisticsView
    _project_filter: str | None
    size: Any

    def _view_renderable(self, result: StatisticsViewData) -> Any:
        views = result.views
        renderable: Any
        if self._view == "overview":
            renderable = self._overview_renderable(views.overview)
        elif self._view == "runs":
            renderable = self._runs_renderable(views.runs)
        elif self._view == "projects":
            return self._projects_renderable(views.projects)
        elif self._view == "providers":
            renderable = self._providers_renderable(views.providers)
        elif self._view == "runtime":
            renderable = self._runtime_renderable(views.runtime)
        elif self._view == "activity":
            renderable = self._activity_renderable(views.activity)
        elif self._view == "plans_questions":
            renderable = self._plans_questions_renderable(views.plans_questions)
        return Group(renderable, self._legend_note(self._view))

    def _overview_renderable(self, overview: Any) -> Group:
        buckets = Table(box=box.SIMPLE, expand=True, show_header=True)
        buckets.add_column("Bucket", style="bold")
        buckets.add_column("Runs", justify="right", style=_CYAN)
        buckets.add_column("Scale", ratio=1)
        maximum = max((bucket.runs for bucket in overview.buckets), default=0)
        for bucket in overview.buckets:
            buckets.add_row(
                bucket.label,
                str(bucket.runs),
                self._share_bar(bucket.runs, maximum),
            )
        providers = self._count_table(
            "Provider", overview.top_providers, include_share=True
        )
        skills = Table(box=box.SIMPLE, expand=True)
        skills.add_column("Skill", style="bold")
        skills.add_column("Uses", justify="right", style=_CYAN)
        skills.add_column("Agents", justify="right")
        for row in overview.top_skills:
            skills.add_row(row.label, str(row.count), str(row.distinct_agents))
        projects = Table(box=box.SIMPLE, expand=True)
        projects.add_column("Project", style="bold", ratio=1)
        projects.add_column("Runs", justify="right", style=_CYAN)
        projects.add_column("Success", justify="right", style=_GREEN)
        for row in overview.top_projects:
            projects.add_row(
                self._project_cell(row.project_key, row.project_label),
                str(row.runs),
                self._percent(row.success_rate),
            )
        mini_table_width = max(24, (max(60, int(self.size.width or 100)) - 4) // 3)
        return Group(
            Panel(buckets, title="Runs over time", border_style=_ACCENT),
            Columns(
                (
                    Panel(providers, title="Top providers", border_style=_CYAN),
                    Panel(skills, title="Top skills", border_style=_GOLD),
                    Panel(projects, title="Top projects", border_style=_GREEN),
                ),
                equal=True,
                expand=True,
                width=mini_table_width,
            ),
        )

    def _runs_renderable(self, runs: Any) -> Group:
        outcomes = self._count_table("Outcome", runs.outcomes, include_share=True)
        lifecycle = Text()
        lifecycle.append(f"In progress  {runs.in_progress}", style=_CYAN)
        lifecycle.append("    ")
        lifecycle.append(f"Waiting  {runs.waiting}", style=_GOLD)
        lifecycle.append("    ")
        lifecycle.append(f"Retry chains  {runs.retry_chains}")
        lifecycle.append(f"  ·  attempts  {runs.retry_attempts}")
        lifecycle.append(f"  ·  kills  {runs.retry_kills}", style=_RED)
        commit_summary = Text(
            f"{runs.commits} commits  ·  {runs.committing_agents} committing agents  ·  "
            f"{runs.average_commits_per_committing_agent:.2f} average per committing agent"
        )
        distribution = self._distribution_table("Commits", runs.commit_distribution)
        repos = self._count_table("Repository", runs.top_repos)
        return Group(
            Panel(outcomes, title="Outcomes", border_style=_ACCENT),
            Panel(lifecycle, title="Run state & retries", border_style=_CYAN),
            Panel(commit_summary, title="Commit attribution", border_style=_GREEN),
            Columns(
                (
                    Panel(
                        distribution,
                        title="Commits per agent",
                        border_style=_GOLD,
                    ),
                    Panel(repos, title="Top target repos", border_style=_CYAN),
                ),
                equal=True,
                expand=True,
            ),
        )

    def _providers_renderable(self, providers: Any) -> Panel:
        table = Table(box=box.SIMPLE, expand=True)
        table.add_column("Provider", style="bold")
        table.add_column("Model")
        table.add_column("Effort")
        table.add_column("Runs", justify="right", style=_CYAN)
        table.add_column("Share", justify="right")
        table.add_column("Success", justify="right", style=_GREEN)
        table.add_column("Avg runtime", justify="right")
        for row in providers.rows:
            table.add_row(
                row.provider,
                row.model,
                row.effort,
                str(row.runs),
                self._percent(row.share),
                self._percent(row.success_rate),
                "—"
                if row.mean_runtime_seconds is None
                else format_duration(row.mean_runtime_seconds),
            )
        return Panel(table, title="Provider → model → effort", border_style=_ACCENT)

    def _runtime_renderable(self, runtime: Any) -> Group:
        table = Table(box=box.SIMPLE, expand=True)
        table.add_column(runtime.group_by.title(), style="bold", ratio=1)
        table.add_column("Runs", justify="right", style=_CYAN)
        table.add_column("Total", justify="right")
        table.add_column("Mean", justify="right")
        table.add_column("p50", justify="right")
        table.add_column("p95", justify="right")
        table.add_column("Max", justify="right")
        table.add_column("Share", justify="right")
        table.add_column("Scale")
        for row in runtime.rows:
            table.add_row(
                row.group_label,
                str(row.runs),
                format_duration(row.total_seconds),
                format_duration(row.mean_seconds),
                format_duration(row.p50_seconds),
                format_duration(row.p95_seconds),
                format_duration(row.max_seconds),
                self._percent(row.share),
                self._share_bar(row.share, 1.0, width=10),
            )
        return Group(
            Panel(
                table,
                title=f"Runtime grouped by {runtime.group_by}",
                border_style=_ACCENT,
            ),
        )

    def _activity_renderable(self, activity: Any) -> Columns:
        skills = self._activity_table("Skill", activity.skills)
        memories = self._activity_table("Memory", activity.memories)
        workspaces = Table(box=box.SIMPLE, expand=True)
        workspaces.add_column("Workspace", style="bold")
        workspaces.add_column("Runs", justify="right", style=_CYAN)
        for row in activity.workspaces:
            workspaces.add_row(
                f"{row.project_label} · {row.workspace_num}",
                str(row.runs),
            )
        return Columns(
            (
                Panel(skills, title="Skills", border_style=_ACCENT),
                Panel(memories, title="Memories", border_style=_CYAN),
                Panel(workspaces, title="Workspaces", border_style=_GOLD),
            ),
            equal=True,
            expand=True,
        )

    def _plans_questions_renderable(self, view: Any) -> Columns:
        unscoped_suffix = " (all projects)" if self._project_filter else ""
        plans_summary = Text(
            f"Proposed  {view.plans_proposed}  ·  Approved  {view.plans_approved}  ·  "
            f"Rejected  {view.plans_rejected}  ·  Pending  {view.plans_pending}"
        )
        tiers = self._count_table(f"Tier{unscoped_suffix}", view.plan_tiers)
        phases = self._distribution_table(
            f"Phases{unscoped_suffix}", view.phases_per_epic
        )
        questions_summary = Text(
            f"Sessions  {view.question_sessions}  ·  Asking agents  {view.asking_agents}"
        )
        question_summary_rows: tuple[Text, ...]
        if self._project_filter:
            question_summary_rows = (
                questions_summary,
                Text(f"Questions{unscoped_suffix}: {view.questions}"),
            )
        else:
            questions_summary.append(f"  ·  Questions  {view.questions}")
            question_summary_rows = (questions_summary,)
        question_sizes = self._distribution_table(
            f"Questions{unscoped_suffix}", view.questions_per_session
        )
        return Columns(
            (
                Panel(
                    Group(
                        plans_summary,
                        tiers,
                        Text(
                            "Mean phases per epic"
                            f"{unscoped_suffix}: {view.mean_phases_per_epic:.2f}",
                            style="dim",
                        ),
                        phases,
                    ),
                    title="Plans",
                    border_style=_ACCENT,
                ),
                Panel(
                    Group(
                        *question_summary_rows,
                        Text(
                            "Mean questions per session"
                            f"{unscoped_suffix}: "
                            f"{view.mean_questions_per_session:.2f}",
                            style="dim",
                        ),
                        question_sizes,
                    ),
                    title="Questions",
                    border_style=_CYAN,
                ),
            ),
            equal=True,
            expand=True,
        )

    @staticmethod
    def _count_table(
        label: str,
        rows: Any,
        *,
        include_share: bool = False,
    ) -> Table:
        table = Table(box=box.SIMPLE, expand=True)
        table.add_column(label, style="bold", ratio=1)
        table.add_column("Count", justify="right", style=_CYAN)
        if include_share:
            table.add_column("Share", justify="right")
            table.add_column("Scale")
        for row in rows:
            values = [row.label, str(row.count)]
            if include_share:
                share = row.share or 0.0
                values.extend(
                    [
                        StatisticsViewsRenderingMixin._percent(share),
                        StatisticsViewsRenderingMixin._share_bar(share, 1.0),
                    ]
                )
            table.add_row(*values)
        return table

    @staticmethod
    def _activity_table(label: str, rows: Any) -> Table:
        table = Table(box=box.SIMPLE, expand=True)
        table.add_column(label, style="bold", ratio=1)
        table.add_column("Count", justify="right", style=_CYAN)
        table.add_column("Agents", justify="right")
        for row in rows:
            table.add_row(row.label, str(row.count), str(row.distinct_agents))
        return table

    @staticmethod
    def _distribution_table(label: str, rows: Any) -> Table:
        table = Table(box=box.SIMPLE, expand=True)
        table.add_column(label, style="bold")
        table.add_column("Count", justify="right", style=_CYAN)
        table.add_column("Scale", ratio=1)
        maximum = max((row.count for row in rows), default=0)
        for row in rows:
            table.add_row(
                row.label,
                str(row.count),
                StatisticsViewsRenderingMixin._share_bar(row.count, maximum),
            )
        return table

    @staticmethod
    def _percent(value: float) -> str:
        return f"{value * 100:.1f}%"

    @staticmethod
    def _share_bar(value: float, maximum: float, *, width: int = 14) -> Text:
        ratio = min(1.0, max(0.0, float(value) / float(maximum))) if maximum else 0.0
        filled = round(ratio * width)
        text = Text()
        text.append("█" * filled, style=_ACCENT)
        text.append("░" * (width - filled), style="#444444")
        return text


__all__ = ["StatisticsViewsRenderingMixin"]
