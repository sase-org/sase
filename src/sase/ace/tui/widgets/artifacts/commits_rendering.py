"""Renderable builders for the Artifacts Stitches pane."""

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
from sase.vcs_log._origin_style import build_origin_detail
from sase.vcs_log._style import GOLD, MERGE, repo_colors
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
    result: VcsLogResult | None,
    refreshing: bool,
    active_limit: int | None = None,
    selected_commit_index: int | None = None,
) -> Text:
    """Build the scope and collection-status header."""
    text = build_commits_info_header(
        refreshing=refreshing,
        active_limit=active_limit,
    )
    text.append("\n")
    text.append_text(
        build_commit_position_badge(
            result=result,
            selected_commit_index=selected_commit_index,
        )
    )
    text.append_text(build_commits_legend(result))
    return text


def build_commits_info_header(
    *,
    refreshing: bool,
    active_limit: int | None = None,
) -> Text:
    """Build the comparatively static first row of the Stitches information area."""
    accent = ARTIFACTS_ACCENTS["stitches"]
    text = Text()
    text.append(" Stitch ", style=f"bold #1a1a1a on {accent}")
    if active_limit is not None:
        text.append("  ", style="dim")
        text.append(f"limit:{active_limit}", style=f"bold {accent}")
    if refreshing:
        text.append("  ·  refreshing…", style="italic #FFD700")
    return text


def build_commit_position_badge(
    *,
    result: VcsLogResult | None,
    selected_commit_index: int | None,
) -> Text:
    """Build ``[position/total]`` from the displayed commit tuple."""
    text = Text(no_wrap=True)
    if result is None:
        return text

    total = len(result.commits)
    if total == 0:
        numerator = "0"
        numerator_style = "bold white"
    elif selected_commit_index is not None and 0 <= selected_commit_index < total:
        numerator = str(selected_commit_index + 1)
        numerator_style = "bold white"
    else:
        numerator = "-"
        numerator_style = "dim"

    denominator = f"{total}{'+' if result.potentially_truncated else ''}"
    text.append("[", style="dim")
    text.append(numerator, style=numerator_style)
    text.append("/", style="dim")
    text.append(denominator, style=f"bold {GOLD}")
    text.append("]  ·  ", style="dim")
    return text


def build_commits_legend(result: VcsLogResult | None) -> Text:
    """Build the cached repository/presence legend beside the position badge."""
    if result is None:
        return Text(
            "  Timeline loads lazily on first activation.",
            style="dim italic",
        )

    legend = build_pretty_legend(
        result,
        visible_repos_only=True,
        show_filter_summary=False,
    )
    # The shared CLI legend owns its leading indentation and, when there are
    # no repositories, a leading separator before the presence key. The TUI
    # places both in dedicated widgets, so trim that presentation-only prefix
    # and let the badge contribute the row's single separator.
    leading_spaces = len(legend.plain) - len(legend.plain.lstrip(" "))
    legend = legend[leading_spaces:]
    if legend.plain.startswith("·  "):
        legend = legend[len("·  ") :]
    if result.warnings:
        legend.append(
            f"  ·  ⚠ {len(result.warnings)} warning(s)",
            style="dim #FFAF5F",
        )
    return legend


def build_commits_hints(registry: KeymapRegistry) -> Text:
    """Build the Stitches action hint bar from configured keymaps."""
    actions = registry.app
    view_key = key_display_name(actions.stitches_view_selected)
    if view_key == "Enter":
        view_key = view_key.lower()
    text = Text(
        f"{key_display_name(actions.stitches_next)}/"
        f"{key_display_name(actions.stitches_prev)} navigate  {view_key} view"
    )
    for key, label in (
        (key_display_name(actions.stitches_copy_sha), "copy"),
        (key_display_name(actions.edit_query), "filter"),
        (key_display_name(actions.stitches_toggle_sdd), "sidecars"),
        (key_display_name(actions.stitches_cycle_merges), "merges"),
        (key_display_name(actions.stitches_toggle_all_projects), "all"),
        (key_display_name(actions.stitches_fetch), "fetch"),
        (key_display_name(actions.stitches_refresh), "refresh"),
        (key_display_name(actions.pick_artifacts_project), "project"),
    ):
        text.append("  ")
        text.append(key)
        text.append(f" {label}")
    return text


def commit_filter_chips(
    filters: CommitLogFilterValues,
) -> tuple[str, ...]:
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
        repo_kind = repo.kind
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
        plan_workspaces=repo.plan_workspaces if repo is not None else (),
        created_at=entry.commit.timestamp,
        parent_ids=entry.commit.parent_ids,
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
    tag_view = commit_tag_view(commit)
    colors = repo_colors(result.repos if result is not None else ())
    header = Text()
    header.append(entry.repo, style=f"bold {colors.get(entry.repo, '#87D7FF')}")
    header.append("  ")
    header.append(commit.short_id, style=GOLD)
    if commit.is_merge:
        header.append("  ◆ merge", style=MERGE)
    if commit.author_name:
        header.append("\nAuthor     ", style="dim")
        header.append(commit.author_name)
    header.append("\nOrigin     ", style="dim")
    header.append_text(
        build_origin_detail(
            commit.origin,
            automation_type=_tag_value(tag_view.tags, "TYPE"),
        )
    )
    if commit.is_merge:
        header.append("\nParents    ", style="dim")
        header.append(
            _short_parent_ids(
                commit.parent_ids,
                width=len(commit.short_id or commit.full_id),
            )
        )
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
    if tag_view.body:
        message.append("\n")
        message.append(tag_view.body.rstrip(), style="#D7D7FF")

    parts: list[RenderableType] = [header, message]
    parts.extend(full_tag_lines(tag_view.tags))
    if commit.is_merge:
        parts.append(
            Text(
                "Changes introduced by this merge (vs first parent)",
                style="bold #87D7FF",
            )
        )
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


def _short_parent_ids(parent_ids: tuple[str, ...], *, width: int) -> str:
    short_width = max(1, width)
    return " ".join(parent_id[:short_width] for parent_id in parent_ids)


def _tag_value(tags: tuple[tuple[str, str], ...], key: str) -> str | None:
    for tag_key, value in tags:
        if tag_key == key:
            return value
    return None
