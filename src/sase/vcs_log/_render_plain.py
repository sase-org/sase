"""Plain-text ``sase stitch list`` renderers — ``json`` and ``oneline``.

Both branches return a plain string (no Rich) so they stay stable under
redirection and machine consumption.
"""

from __future__ import annotations

from dataclasses import asdict
import json

from sase.core.vcs_log_facade import merge_summary
from sase.core.vcs_log_wire import AggregatedCommitWire
from sase.vcs_log.models import CommitFilters, LogRepo, RepoRemoteState, VcsLogResult
from sase.vcs_log._origin_style import origin_glyph
from sase.vcs_log._render_util import presence_glyph
from sase.vcs_log.tags import commit_tag_view


# ---------------------------------------------------------------------------
# json
# ---------------------------------------------------------------------------


def render_json(
    result: VcsLogResult,
    commits: tuple[AggregatedCommitWire, ...],
    limit: int,
    filters: CommitFilters,
    reverse: bool,
    show_tags: bool,
    all_projects: bool,
) -> str:
    states = {state.name: state for state in result.remote_states}
    payload = {
        "repos": [_repo_json(repo, states) for repo in result.repos],
        "commits": [_commit_json(entry, show_tags=show_tags) for entry in commits],
        "query": {
            "all": all_projects,
            "limit": limit,
            "since": filters.since,
            "until": filters.until,
            "authors": list(filters.authors),
            "merges": filters.merges,
            "reverse": reverse,
        },
        "warnings": list(result.warnings),
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _commit_json(entry: AggregatedCommitWire, *, show_tags: bool) -> dict[str, object]:
    item: dict[str, object] = {
        "repo": entry.repo,
        "full_id": entry.commit.full_id,
        "short_id": entry.commit.short_id,
        "author_name": entry.commit.author_name,
        "author_email": entry.commit.author_email,
        "timestamp": entry.commit.timestamp,
        "parent_ids": list(entry.commit.parent_ids),
        "is_merge": entry.commit.is_merge,
        "merge": _merge_json(entry),
        "subject": entry.commit.subject,
        "presence": entry.commit.presence,
        "origin": entry.commit.origin,
    }
    if show_tags:
        item["sase_tags"] = dict(commit_tag_view(entry.commit).tags)
    return item


def _repo_json(repo: LogRepo, states: dict[str, RepoRemoteState]) -> dict[str, object]:
    state = states.get(repo.name, RepoRemoteState(repo.name, None, 0, 0, False))
    return {
        "name": repo.name,
        "kind": repo.kind,
        "path": repo.path,
        "remote_ref": state.remote_ref,
        "ahead": state.ahead,
        "behind": state.behind,
        "fetched": state.fetched,
        "fetched_at": state.fetched_at,
    }


# ---------------------------------------------------------------------------
# oneline
# ---------------------------------------------------------------------------


def render_oneline(
    commits: tuple[AggregatedCommitWire, ...], *, show_tags: bool
) -> str:
    if not commits:
        return ""
    repo_width = max(len(entry.repo) for entry in commits)
    sha_width = max(len(entry.commit.short_id) for entry in commits)
    merge_column = any(entry.commit.is_merge for entry in commits)
    lines = [
        f"{presence_glyph(entry.commit.presence)} "
        f"{entry.commit.short_id.ljust(sha_width)} "
        f"{entry.repo.ljust(repo_width)} "
        f"{_oneline_merge_marker(entry) if merge_column else ''}"
        f"{origin_glyph(entry.commit.origin)} "
        f"{entry.commit.subject}"
        f"{_oneline_tag_suffix(entry) if show_tags else ''}"
        for entry in commits
    ]
    return "\n".join(lines) + "\n"


def _merge_json(entry: AggregatedCommitWire) -> dict[str, object] | None:
    if not entry.commit.is_merge:
        return None
    summary = merge_summary(entry.commit.subject, entry.commit.body)
    return asdict(summary) if summary is not None else None


def _oneline_merge_marker(entry: AggregatedCommitWire) -> str:
    return "◆ " if entry.commit.is_merge else "  "


def _oneline_tag_suffix(entry: AggregatedCommitWire) -> str:
    tags = commit_tag_view(entry.commit).tags
    if not tags:
        return ""
    return f" [{_format_tags(tags, separator=' ')}]"


def _format_tags(tags: tuple[tuple[str, str], ...], *, separator: str) -> str:
    return separator.join(f"{key}={value}" for key, value in tags)
