"""Time-band chrome for memory-history pager sections.

Facade over the split modules: vocabulary and sparkline primitives in
:mod:`sase.pager._time_band_vocab`, the timeline model in
:mod:`sase.pager._time_band_model`, and row rendering in
:mod:`sase.pager._time_band_render`. Import public names from here; the
sibling modules are the source of truth.
"""

from __future__ import annotations

from sase.pager._time_band_model import TimeBandData
from sase.pager._time_band_model import TimeBandTarget
from sase.pager._time_band_model import build_time_band_data
from sase.pager._time_band_model import ref_for_target
from sase.pager._time_band_model import time_band_targets
from sase.pager._time_band_render import render_time_band
from sase.pager._time_band_vocab import ALIAS_SEPARATOR
from sase.pager._time_band_vocab import BAND_LABEL_STYLE
from sase.pager._time_band_vocab import CLASS_GLYPHS
from sase.pager._time_band_vocab import DELETED_STYLE
from sase.pager._time_band_vocab import DIM_STYLE
from sase.pager._time_band_vocab import DIVERGED_CHIP
from sase.pager._time_band_vocab import HIDDEN_CELL
from sase.pager._time_band_vocab import HIDDEN_CLASSES
from sase.pager._time_band_vocab import NO_HISTORY_HONEST
from sase.pager._time_band_vocab import PAST_STYLE
from sase.pager._time_band_vocab import SPARKLINE_BLOCKS
from sase.pager._time_band_vocab import TimeState
from sase.pager._time_band_vocab import UNCOMMITTED_STYLE
from sase.pager._time_band_vocab import chrome_row_budget
from sase.pager._time_band_vocab import format_age
from sase.pager._time_band_vocab import render_scrubber
from sase.pager._time_band_vocab import render_sparkline
from sase.pager._time_band_vocab import short_display_for_subject_id


__all__ = [
    "ALIAS_SEPARATOR",
    "BAND_LABEL_STYLE",
    "CLASS_GLYPHS",
    "DELETED_STYLE",
    "DIM_STYLE",
    "DIVERGED_CHIP",
    "HIDDEN_CELL",
    "HIDDEN_CLASSES",
    "NO_HISTORY_HONEST",
    "PAST_STYLE",
    "SPARKLINE_BLOCKS",
    "TimeBandData",
    "TimeBandTarget",
    "TimeState",
    "UNCOMMITTED_STYLE",
    "build_time_band_data",
    "chrome_row_budget",
    "format_age",
    "ref_for_target",
    "render_scrubber",
    "render_sparkline",
    "render_time_band",
    "short_display_for_subject_id",
    "time_band_targets",
]
