"""Shared rendering primitives for agent-list rows.

Houses style constants and small layout helpers (tier gutter, runtime
suffix builders, padded-Option assembly) that are reused by the agent,
banner, and attempt row formatters.
"""

from datetime import datetime

from rich.text import Text
from textual.widgets.option_list import Option

from sase.agent.status_buckets import agent_is_asking, agent_status_bucket

from ..models import agent_time as agent_time_model
from ..models.agent import (
    Agent,
    AttemptRecord,
    compute_row_runtime,
    format_compact_duration,
)
from ..models.agent_family_members import current_family_shell_row
from ._agent_list_styling import _TIER_GUIDE_SEGMENT

# Timestamp half: muted lavender-steel.  No `dim` attribute so the color
# carries on its own; chosen to harmonize with WAITING amethyst (#AF87FF)
# and project-banner sky-blue (#5FAFFF) while staying clearly less
# saturated, so the timestamp reads as a "metadata column" rather than a
# status word.
_RUNTIME_TS_STYLE = "#8787AF"
# Date prefix half (e.g. "Apr 26 ", "Apr 26 '25"): same hue as the time
# half but dimmed so the date reads as context while the time stays the
# salient anchor when scanning rows.
_RUNTIME_DATE_STYLE = "dim #8787AF"
# Elapsed half: light neutral grey, bold to give the headline number
# ("how long?") a little more weight than the timestamp without using
# a saturated color.  Readable on dark and light themes alike.
_RUNTIME_ELAPSED_STYLE = "bold #BCBCBC"
# Live marker: soft gold so active second-by-second runtimes are scannable
# without competing with the row's status color.
_RUNTIME_LIVE_MARKER = "🏃‍♂️ "
_RUNTIME_LIVE_MARKER_STYLE = "#D7AF5F"
# Completed-unread markers: occupy the same suffix slot as the live marker
# so newly finished unseen rows scan where active runtimes did. The check
# marker is used for non-failed terminal rows; the X marker for any row
# whose status falls in the Failed bucket.
_RUNTIME_UNREAD_DONE_MARKER = "✅ "
_RUNTIME_UNREAD_FAILED_MARKER = "❌ "
# Emoji glyphs render in their intrinsic colors in modern terminals; the
# foreground style only affects the trailing space, so a single style serves
# both variants.
_RUNTIME_UNREAD_MARKER_STYLE = "#5FD7FF"
# User-paused marker: same suffix slot, used when the row is waiting on
# an explicit user action instead of active runtime.
_RUNTIME_USER_PAUSED_MARKER = "✋ "
_RUNTIME_USER_PAUSED_MARKER_STYLE = "#FFAF5F"


def _runtime_suffix_user_paused(agent: Agent, *, is_ticking: bool) -> bool:
    return agent_is_asking(agent.status) and not is_ticking


def _unread_marker(agent: Agent) -> str:
    if agent_status_bucket(agent) == "Failed":
        return _RUNTIME_UNREAD_FAILED_MARKER
    return _RUNTIME_UNREAD_DONE_MARKER


def render_tier_gutter(tier_styles: tuple[str, ...]) -> Text:
    """Build the leading tier-guide gutter for a row.

    Emits one ``│  `` segment per supplied style, in order from outermost
    (project / bucket) to innermost (Patch).  Returns an empty Text
    when *tier_styles* is empty so callers can prepend unconditionally.
    """
    gutter = Text()
    for style in tier_styles:
        gutter.append(_TIER_GUIDE_SEGMENT, style=style)
    return gutter


def build_runtime_suffix(
    agent: Agent,
    now: datetime | None = None,
    *,
    is_unread: bool = False,
) -> Text:
    """Return a Rich ``Text`` for the right-side runtime suffix (may be empty)."""
    reference = now if now is not None else agent_time_model.local_now()
    ts_pair, elapsed = compute_row_runtime(agent, now=reference)
    suffix = Text()
    is_ticking = agent_time_model.runtime_suffix_ticks(agent)
    current_shell_elapsed: str | None = None
    if elapsed is not None and is_ticking:
        current_shell = current_family_shell_row(agent)
        if current_shell is not None:
            _shell_ts_pair, current_shell_elapsed = (
                agent_time_model.compute_leaf_row_runtime(
                    current_shell,
                    now=reference,
                )
            )
    show_unread_marker = is_unread and not is_ticking
    show_user_paused_marker = (
        _runtime_suffix_user_paused(agent, is_ticking=is_ticking)
        and not show_unread_marker
    )
    if ts_pair is None and elapsed is None:
        if show_unread_marker:
            suffix.append(
                _unread_marker(agent).rstrip(),
                style=_RUNTIME_UNREAD_MARKER_STYLE,
            )
        elif show_user_paused_marker:
            suffix.append(
                _RUNTIME_USER_PAUSED_MARKER.rstrip(),
                style=_RUNTIME_USER_PAUSED_MARKER_STYLE,
            )
        return suffix
    if ts_pair is not None:
        date_part, time_part = ts_pair
        if date_part:
            suffix.append(date_part, style=_RUNTIME_DATE_STYLE)
        if time_part:
            suffix.append(time_part, style=_RUNTIME_TS_STYLE)
        suffix.append(" · ", style=_RUNTIME_TS_STYLE)
    if elapsed is not None:
        if is_ticking:
            suffix.append(_RUNTIME_LIVE_MARKER, style=_RUNTIME_LIVE_MARKER_STYLE)
        elif show_unread_marker:
            suffix.append(
                _unread_marker(agent),
                style=_RUNTIME_UNREAD_MARKER_STYLE,
            )
        elif show_user_paused_marker:
            suffix.append(
                _RUNTIME_USER_PAUSED_MARKER,
                style=_RUNTIME_USER_PAUSED_MARKER_STYLE,
            )
        if current_shell_elapsed is not None:
            suffix.append(current_shell_elapsed, style=_RUNTIME_ELAPSED_STYLE)
            suffix.append(" / ")
        suffix.append(elapsed, style=_RUNTIME_ELAPSED_STYLE)
    elif show_unread_marker:
        suffix.append(
            _unread_marker(agent).rstrip(),
            style=_RUNTIME_UNREAD_MARKER_STYLE,
        )
    elif show_user_paused_marker:
        suffix.append(
            _RUNTIME_USER_PAUSED_MARKER.rstrip(),
            style=_RUNTIME_USER_PAUSED_MARKER_STYLE,
        )
    return suffix


def build_attempt_runtime_suffix(record: AttemptRecord) -> Text:
    """Return a Rich ``Text`` with the attempt's elapsed duration (may be empty)."""
    suffix = Text()
    duration_secs = record.end_epoch - record.start_epoch
    if duration_secs > 0:
        suffix.append(
            format_compact_duration(duration_secs), style=_RUNTIME_ELAPSED_STYLE
        )
    return suffix


def assemble_padded_option(
    left: Text,
    suffix: Text,
    *,
    width: int,
    option_id: str,
    disabled: bool = False,
) -> Option:
    """Combine ``left`` and ``suffix`` into a single Option, right-aligned.

    Pads with spaces so the suffix's right edge sits at ``width`` cells,
    falling back to a 2-cell gap when ``left + suffix`` already meets or
    exceeds ``width``.  Rows whose suffix is empty render with no padding
    at all (their column is just left content).
    """
    if suffix.cell_len == 0:
        return Option(left, id=option_id, disabled=disabled)
    pad_len = max(2, width - left.cell_len - suffix.cell_len)
    combined = Text()
    combined.append_text(left)
    combined.append(" " * pad_len)
    combined.append_text(suffix)
    return Option(combined, id=option_id, disabled=disabled)
