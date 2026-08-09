"""Shared helpers for the ``sase vcs log`` renderers.

Presence glyphs/labels, commit ordering, filter summaries, remote-state
summaries, and wall-clock formatting live here so the plain-text and Rich
renderers stay free of formatting trivia. All wall-clock formatting goes
through :mod:`sase.core.time` so it respects the configured timezone;
sorting stays epoch-based upstream and is timezone-immune.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from rich.text import Text

from sase.core.vcs_log_wire import AggregatedCommitWire, CommitPresence
from sase.vcs_log.models import CommitFilters, RepoRemoteState, VcsLogResult
from sase.vcs_log._style import INCOMING, UNPUSHED

_PRESENCE_GLYPHS: dict[CommitPresence, str] = {
    "synced": "●",
    "remote_only": "↓",
    "local_only": "↑",
    "unknown": "·",
}
_PRESENCE_LABELS: dict[CommitPresence, str] = {
    "synced": "synced",
    "remote_only": "GitHub-only",
    "local_only": "unpushed",
    "unknown": "unknown",
}


# ---------------------------------------------------------------------------
# presence
# ---------------------------------------------------------------------------


def presence_glyph(presence: CommitPresence) -> str:
    return _PRESENCE_GLYPHS.get(presence, _PRESENCE_GLYPHS["unknown"])


def presence_style(presence: CommitPresence, repo_color: str) -> str | None:
    if presence == "remote_only":
        return INCOMING
    if presence == "local_only":
        return UNPUSHED
    if presence == "unknown":
        return "dim"
    return repo_color or None


def presence_label(presence: CommitPresence) -> str:
    return _PRESENCE_LABELS.get(presence, _PRESENCE_LABELS["unknown"])


def build_commit_presence(
    presence: CommitPresence,
    *,
    repo_color: str = "",
) -> Text:
    """Build the shared glyph and human-readable label for a presence state."""
    text = Text()
    text.append(
        f"{presence_glyph(presence)} {presence_label(presence)}",
        style=presence_style(presence, repo_color),
    )
    return text


# ---------------------------------------------------------------------------
# commits and filters
# ---------------------------------------------------------------------------


def ordered_commits(
    result: VcsLogResult,
    *,
    filters: CommitFilters,
    limit: int,
    reverse: bool,
) -> tuple[AggregatedCommitWire, ...]:
    # Providers use coarse date filtering. Apply SASE's exact inclusive
    # author-time bounds before the user-visible cap so boundary-margin
    # candidates cannot consume output rows.
    commits = tuple(
        entry
        for entry in result.commits
        if (filters.since is None or entry.commit.timestamp >= filters.since)
        and (filters.until is None or entry.commit.timestamp <= filters.until)
    )
    if limit > 0:
        commits = commits[:limit]
    return tuple(reversed(commits)) if reverse else commits


def filter_summary(filters: CommitFilters) -> str:
    parts: list[str] = []
    if filters.since is not None:
        parts.append(f"since {_format_bound(filters.since)}")
    if filters.until is not None:
        parts.append(f"until {_format_bound(filters.until)}")
    if filters.authors:
        parts.append(f"author {' or '.join(filters.authors)}")
    if filters.merges == "only":
        parts.append("merges only")
    elif filters.merges == "show":
        parts.append("with merges")
    return " · ".join(parts)


def empty_message(filters: CommitFilters) -> str:
    summary = filter_summary(filters).replace(" · ", ", ")
    label = "No merge commits found" if filters.merges == "only" else "No commits found"
    if not summary:
        return label
    return f"{label} ({summary})"


def _format_bound(timestamp: int) -> str:
    dt_local = to_local(timestamp)
    if (
        dt_local.hour,
        dt_local.minute,
        dt_local.second,
        dt_local.microsecond,
    ) == (0, 0, 0, 0):
        return f"{dt_local:%Y-%m-%d}"
    if dt_local.second or dt_local.microsecond:
        return f"{dt_local:%Y-%m-%dT%H:%M:%S}"
    return f"{dt_local:%Y-%m-%dT%H:%M}"


# ---------------------------------------------------------------------------
# remote state
# ---------------------------------------------------------------------------


def remote_state(result: VcsLogResult, repo_name: str) -> RepoRemoteState:
    for state in result.remote_states:
        if state.name == repo_name:
            return state
    return RepoRemoteState(repo_name, None, 0, 0, False)


def remote_summary(states: tuple[RepoRemoteState, ...]) -> str:
    known = [state for state in states if state.remote_ref]
    if not known:
        return ""
    refs = {state.remote_ref for state in known}
    if len(refs) == 1:
        ref_text = next(iter(refs)) or ""
    else:
        ref_text = ", ".join(f"{state.name}={state.remote_ref}" for state in known)
    fetch_text = _remote_fetch_summary(known)
    return f"vs {ref_text} · {fetch_text}"


def _remote_fetch_summary(states: list[RepoRemoteState]) -> str:
    if all(state.fetched for state in states):
        return "fetched"
    if all(state.fetched_at is not None and not state.fetched for state in states):
        fetched_at = min(
            state.fetched_at for state in states if state.fetched_at is not None
        )
        return f"fetched {_format_fetch_age(fetched_at)}"
    if all(state.fetched or state.fetched_at is not None for state in states):
        return "fresh"
    if any(state.fetched or state.fetched_at is not None for state in states):
        return "partly fetched"
    return "not fetched"


def _format_fetch_age(fetched_at: float) -> str:
    age_seconds = max(0, int(_now_epoch() - fetched_at))
    if age_seconds < 60:
        return f"{age_seconds}s ago"
    minutes = age_seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


def _now_epoch() -> float:
    return time.time()


# ---------------------------------------------------------------------------
# wall clock
# ---------------------------------------------------------------------------


def to_local(timestamp: int) -> datetime:
    from sase.core.time import to_local as _core_to_local

    return _core_to_local(datetime.fromtimestamp(timestamp, tz=UTC))


def local_now() -> datetime:
    from sase.core.time import local_now as _core_local_now

    return _core_local_now()


def day_label(dt_local: datetime, now_local: datetime) -> str:
    day = dt_local.date()
    today = now_local.date()
    if day == today:
        return "Today"
    if day == today - timedelta(days=1):
        return "Yesterday"
    if day.year == today.year:
        return f"{dt_local:%b} {dt_local.day}"
    return f"{dt_local:%b} {dt_local.day}, {dt_local.year}"


def relative_age(dt_local: datetime) -> str:
    return relative_age_between(dt_local, local_now())


def relative_age_between(dt_local: datetime, now_local: datetime) -> str:
    total_seconds = int((now_local - dt_local).total_seconds())
    if total_seconds <= 0:
        return "just now"
    if total_seconds < 60:
        return f"{total_seconds}s ago"
    minutes = total_seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"
