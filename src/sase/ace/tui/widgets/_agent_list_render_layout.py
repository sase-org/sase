"""Shared rendering primitives for agent-list rows.

Houses style constants and small layout helpers (tier gutter, runtime
suffix builders, padded-Option assembly) that are reused by the agent,
banner, and attempt row formatters.
"""

from datetime import datetime

from rich.text import Text
from textual.widgets.option_list import Option

from ..models.agent import (
    Agent,
    AttemptRecord,
    compute_row_runtime,
    format_compact_duration,
)
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


def render_tier_gutter(tier_styles: tuple[str, ...]) -> Text:
    """Build the leading tier-guide gutter for a row.

    Emits one ``│  `` segment per supplied style, in order from outermost
    (project / bucket) to innermost (ChangeSpec).  Returns an empty Text
    when *tier_styles* is empty so callers can prepend unconditionally.
    """
    gutter = Text()
    for style in tier_styles:
        gutter.append(_TIER_GUIDE_SEGMENT, style=style)
    return gutter


def build_runtime_suffix(agent: Agent, now: datetime | None = None) -> Text:
    """Return a Rich ``Text`` for the right-side runtime suffix (may be empty)."""
    ts_pair, elapsed = compute_row_runtime(agent, now=now)
    suffix = Text()
    if ts_pair is None and elapsed is None:
        return suffix
    if ts_pair is not None:
        date_part, time_part = ts_pair
        if date_part:
            suffix.append(date_part, style=_RUNTIME_DATE_STYLE)
        if time_part:
            suffix.append(time_part, style=_RUNTIME_TS_STYLE)
        suffix.append(" · ", style=_RUNTIME_TS_STYLE)
    if elapsed is not None:
        suffix.append(elapsed, style=_RUNTIME_ELAPSED_STYLE)
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
