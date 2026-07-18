"""Renderable builders for the Artifacts commits pane."""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.text import Text

from sase.ace.tui.keymaps import KeymapRegistry, key_display_name
from sase.ace.tui.util.lazy_syntax import (
    PLAIN_RENDER_MAX_LINES,
    LazySyntaxRenderCache,
    lazy_renderable,
)
from sase.ace.tui.widgets.prompt_panel._agent_deltas import parse_unified_diff_deltas
from sase.ace.tui.widgets.prompt_panel._agent_display_state import CommitViewSpec
from sase.core.vcs_log_wire import AggregatedCommitWire
from sase.repo_inventory import RepoKind
from sase.vcs_log._style import GOLD, repo_colors
from sase.vcs_log._tag_style import full_tag_lines
from sase.vcs_log.filter_query import to_query_tokens
from sase.vcs_log.models import VcsLogResult
from sase.vcs_log.render import (
    build_commit_presence,
    build_pretty_legend,
    format_commit_timestamp,
)
from sase.vcs_log.tags import commit_tag_view

from .commit_filters import CommitLogFilterValues
from .types import ARTIFACTS_ACCENTS


def build_commits_info(
    *,
    project_display_name: str | None,
    project_scope: str | None,
    all_projects: bool,
    include_sdd: bool,
    filters: CommitLogFilterValues,
    result: VcsLogResult | None,
    refreshing: bool,
) -> Text:
    """Build the scope, filter, and collection-status header."""
    accent = ARTIFACTS_ACCENTS["commits"]
    scope = (
        "All projects"
        if all_projects
        else project_display_name or project_scope or "Current project"
    )
    text = Text()
    text.append(" Commits ", style=f"bold #1a1a1a on {accent}")
    text.append("  Scope ", style="dim")
    text.append(scope, style=f"bold {accent}")
    text.append("  ·  ", style="dim")
    text.append(
        "SDD on" if include_sdd else "SDD off",
        style="bold" if include_sdd else "dim",
    )
    for chip in commit_filter_chips(filters):
        text.append("  ·  ", style="dim")
        text.append(chip, style="dim #87D7FF")
    if refreshing:
        text.append("  ·  refreshing…", style="italic #FFD700")
    if result is not None:
        text.append("\n")
        text.append_text(build_pretty_legend(result, filters=filters.backend_filters()))
        if result.warnings:
            text.append(
                f"  ·  ⚠ {len(result.warnings)} warning(s)",
                style="dim #FFAF5F",
            )
    else:
        text.append(
            "\n  Timeline loads lazily on first activation.", style="dim italic"
        )
    return text


def build_commits_hints(registry: KeymapRegistry) -> Text:
    """Build the commits action hint bar from configured keymaps."""
    actions = registry.app
    view_key = key_display_name(actions.commits_view_selected)
    if view_key == "Enter":
        view_key = view_key.lower()
    text = Text(
        f"{key_display_name(actions.commits_next)}/"
        f"{key_display_name(actions.commits_prev)} navigate  {view_key} view"
    )
    for key, label in (
        (actions.commits_copy_sha, "copy"),
        (actions.edit_query, "filter"),
        (actions.commits_toggle_sdd, "SDD"),
        (actions.commits_toggle_all_projects, "all"),
        (actions.commits_fetch, "fetch"),
        (actions.commits_refresh, "refresh"),
        (actions.pick_artifacts_project, "project"),
    ):
        text.append("  ")
        text.append(key_display_name(key))
        text.append(f" {label}")
    return text


def commit_filter_chips(filters: CommitLogFilterValues) -> tuple[str, ...]:
    """Return active filters in the same vocabulary as the query language."""
    return to_query_tokens(filters)


def build_commit_view_spec(
    entry: AggregatedCommitWire,
    result: VcsLogResult | None,
) -> CommitViewSpec:
    """Translate an aggregated commit into the shared modal/diff view model."""
    repo = (
        next((repo for repo in result.repos if repo.name == entry.repo), None)
        if result is not None
        else None
    )
    repo_kind: RepoKind = "linked"
    if repo is not None:
        repo_kind = (
            "primary"
            if repo.kind == "primary"
            else "sidecar"
            if repo.kind == "sdd"
            else "linked"
        )
    message = entry.commit.subject
    if entry.commit.body:
        message = f"{message}\n\n{entry.commit.body}"
    return CommitViewSpec(
        short_sha=entry.commit.short_id,
        sha=entry.commit.full_id,
        repo_name=entry.repo,
        cwd=repo.path if repo is not None else None,
        subject=entry.commit.subject,
        message=message,
        diff_path=None,
        is_primary=repo_kind == "primary",
        repo_kind=repo_kind,
    )


def build_commit_detail(
    entry: AggregatedCommitWire,
    diff_text: str | None,
    *,
    loading: bool,
    result: VcsLogResult | None,
    render_cache: LazySyntaxRenderCache,
) -> RenderableType:
    """Build the selected commit's metadata, summary, and lazy diff."""
    commit = entry.commit
    colors = repo_colors(result.repos if result is not None else ())
    header = Text()
    header.append(entry.repo, style=f"bold {colors.get(entry.repo, '#87D7FF')}")
    header.append("  ")
    header.append(commit.short_id, style=GOLD)
    if commit.author_name:
        header.append("\nAuthor     ", style="dim")
        header.append(commit.author_name)
    header.append("\nCommitted  ", style="dim")
    header.append(format_commit_timestamp(commit.timestamp))
    header.append("\nPresence   ", style="dim")
    header.append_text(
        build_commit_presence(
            commit.presence,
            repo_color=colors.get(entry.repo, "#87D7FF"),
        )
    )

    message = Text()
    message.append("Message\n", style="bold #87D7FF")
    message.append(commit.subject or "(message unavailable)", style="bold #D7D7FF")
    tag_view = commit_tag_view(commit)
    if tag_view.body:
        message.append("\n")
        message.append(tag_view.body.rstrip(), style="#D7D7FF")

    parts: list[RenderableType] = [header, message]
    parts.extend(full_tag_lines(tag_view.tags))
    summary = _change_summary(diff_text)
    if summary is not None:
        parts.append(summary)
    parts.append(Text("─" * 72, style="dim"))
    if loading:
        parts.append(Text("Loading diff…", style="dim italic #87D7FF"))
    elif diff_text:
        parts.append(
            lazy_renderable(
                diff_text,
                "diff",
                line_numbers=True,
                theme="monokai",
                render_cache=render_cache,
                max_render_lines=PLAIN_RENDER_MAX_LINES,
                truncation_hint=(
                    f"run git show {commit.short_id} in {entry.repo} "
                    "to see the full diff"
                ),
            )
        )
    else:
        parts.append(
            Text("Diff unavailable for this commit.", style="dim italic #87D7FF")
        )
    return Group(*parts)


def _change_summary(diff_text: str | None) -> Text | None:
    if not diff_text:
        return None
    entries = parse_unified_diff_deltas(diff_text)
    if not entries:
        return None
    added = modified = removed = 0
    for entry in entries:
        if entry.line_stats is None:
            continue
        added += entry.line_stats.added
        modified += entry.line_stats.modified
        removed += entry.line_stats.removed
    suffix = "file" if len(entries) == 1 else "files"
    text = Text("Changes: ", style="bold #87D7FF")
    text.append(f"+{added}", style="bold #5FD787")
    text.append(f"  ~{modified}", style="bold #FFD787")
    text.append(f"  -{removed}", style="bold #FF5F5F")
    text.append(f"  ·  {len(entries)} {suffix}", style="dim #87D7FF")
    return text
