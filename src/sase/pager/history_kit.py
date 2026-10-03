"""Public history presentation kit for memory-history surfaces.

Thin, Textual-free re-export facade over the pager's pure history
renderers (epic design ``plan:202610/memory_history_tui.md`` §5.3), so
the kit can never drift from the pager. ACE uses only this door for
history presentation: a guard test fails any direct ``sase.ace``
import of the pager private modules below.

If a pager epic moves a re-exported name, update the import here in
the same change.
"""

from __future__ import annotations

from sase.memory.history.feed_model import FEED_WINDOW as FEED_WINDOW
from sase.memory.history.feed_model import (
    MAX_INLINE_SECTIONS as MAX_INLINE_SECTIONS,
)
from sase.memory.history.feed_model import changeset_row_text as changeset_row_text
from sase.memory.history.feed_model import changeset_view as changeset_view
from sase.memory.history.feed_model import changeset_word_delta as changeset_word_delta
from sase.memory.history.feed_model import day_header as day_header
from sase.memory.history.feed_model import day_key as day_key
from sase.memory.history.feed_model import dedupe_changesets as dedupe_changesets
from sase.memory.history.feed_model import filter_changesets as filter_changesets
from sase.memory.history.feed_model import flatten_visible as flatten_visible
from sase.memory.history.feed_model import format_clock as format_clock
from sase.memory.history.feed_model import group_feed as group_feed
from sase.memory.history.feed_model import older_window_text as older_window_text
from sase.memory.history.feed_model import provenance_items as provenance_items
from sase.memory.history.feed_model import regen_count_text as regen_count_text
from sase.memory.history.feed_model import window_changesets as window_changesets
from sase.memory.history.feed_model import words_suffix as words_suffix
from sase.memory.history.pager_provider_timelines import (
    dirty_now_from_timeline as dirty_now_from_timeline,
)
from sase.memory.history.pager_provider_timelines import (
    history_marks_from_comparison as history_marks_from_comparison,
)
from sase.memory.history.pager_provider_timelines import (
    is_deleted_row as is_deleted_row,
)
from sase.memory.history.pager_provider_timelines import (
    newest_committed_row as newest_committed_row,
)
from sase.memory.history.pager_provider_timelines import (
    visible_ordinals_for_timeline as visible_ordinals_for_timeline,
)
from sase.memory.history.timeline_picker import (
    build_picker_rows as build_picker_rows,
)
from sase.memory.history.timeline_picker import (
    filter_picker_rows as filter_picker_rows,
)
from sase.memory.history.timeline_picker import (
    hidden_picker_rows as hidden_picker_rows,
)
from sase.memory.history.timeline_picker import (
    hidden_summary_text as hidden_summary_text,
)
from sase.memory.history.timeline_picker import (
    picker_footer_preview as picker_footer_preview,
)
from sase.memory.history.timeline_picker import (
    picker_header_text as picker_header_text,
)
from sase.memory.history.timeline_picker import (
    picker_pill_text as picker_pill_text,
)
from sase.memory.history.timeline_picker import (
    visible_picker_rows as visible_picker_rows,
)
from sase.memory.history.vocabulary import glyph_for as glyph_for
from sase.memory.history.vocabulary import label_for as label_for
from sase.pager._chrome_history import history_badge as history_badge
from sase.pager._chrome_history import history_context as history_context
from sase.pager._chrome_history import honest_chip as honest_chip
from sase.pager._chrome_history import time_verbs_for_moment as time_verbs_for_moment
from sase.pager._time_band import TimeBandData as TimeBandData
from sase.pager._time_band import build_time_band_data as build_time_band_data
from sase.pager._time_band import chrome_row_budget as chrome_row_budget
from sase.pager._time_band import format_age as format_age
from sase.pager._time_band import render_scrubber as render_scrubber
from sase.pager._time_band import render_sparkline as render_sparkline
from sase.pager._time_band import render_time_band as render_time_band
from sase.pager._time_band import time_band_targets as time_band_targets
from sase.pager._time_band_render_meaning import cause_row as cause_row
from sase.pager._time_band_render_meaning import meaning_row as meaning_row
from sase.pager._timeline_picker_rows import PickerColumns as PickerColumns
from sase.pager._timeline_picker_rows import format_picker_row as format_picker_row
from sase.pager._timeline_picker_rows import picker_columns as picker_columns
from sase.pager.history.diff import build_diff_body as build_diff_body
from sase.pager.history.diff import diff_endpoints as diff_endpoints
from sase.pager.history.models import SectionTimeState as SectionTimeState
from sase.pager.history.models import VersionPin as VersionPin
from sase.pager.history.models import (
    committed_pin_for_ordinal as committed_pin_for_ordinal,
)
from sase.pager.history.models import live_pin_for_subject as live_pin_for_subject
from sase.pager.history.moment import VersionMoment as VersionMoment
from sase.pager.history.moment import boundary_notice as boundary_notice
from sase.pager.history.moment import build_moment as build_moment
from sase.pager.history.moment import canonical_ordinal as canonical_ordinal
from sase.pager.history.moment import moment_for_state as moment_for_state
from sase.pager.history.moment import step_target as step_target
from sase.pager.history.styles import HistoryStyles as HistoryStyles
from sase.pager.history.styles import default_history_styles as default_history_styles
from sase.pager.history.styles import (
    history_styles_for_theme as history_styles_for_theme,
)

__all__ = [
    "FEED_WINDOW",
    "HistoryStyles",
    "MAX_INLINE_SECTIONS",
    "PickerColumns",
    "SectionTimeState",
    "TimeBandData",
    "VersionMoment",
    "VersionPin",
    "boundary_notice",
    "build_diff_body",
    "build_moment",
    "build_picker_rows",
    "build_time_band_data",
    "canonical_ordinal",
    "cause_row",
    "changeset_row_text",
    "changeset_view",
    "changeset_word_delta",
    "chrome_row_budget",
    "committed_pin_for_ordinal",
    "day_header",
    "day_key",
    "dedupe_changesets",
    "default_history_styles",
    "diff_endpoints",
    "dirty_now_from_timeline",
    "filter_changesets",
    "filter_picker_rows",
    "flatten_visible",
    "format_age",
    "format_clock",
    "format_picker_row",
    "glyph_for",
    "group_feed",
    "hidden_picker_rows",
    "hidden_summary_text",
    "history_badge",
    "history_context",
    "history_marks_from_comparison",
    "history_styles_for_theme",
    "honest_chip",
    "is_deleted_row",
    "label_for",
    "live_pin_for_subject",
    "meaning_row",
    "moment_for_state",
    "newest_committed_row",
    "older_window_text",
    "picker_columns",
    "picker_footer_preview",
    "picker_header_text",
    "picker_pill_text",
    "provenance_items",
    "regen_count_text",
    "render_scrubber",
    "render_sparkline",
    "render_time_band",
    "step_target",
    "time_band_targets",
    "time_verbs_for_moment",
    "visible_ordinals_for_timeline",
    "visible_picker_rows",
    "window_changesets",
    "words_suffix",
]
