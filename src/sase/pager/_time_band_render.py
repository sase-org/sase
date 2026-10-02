"""Row renderers for the pager time band.

Facade preserving the original :mod:`sase.pager._time_band_render`
import path. The band orchestration plus life-strip, timeline, and
tombstone rows live in :mod:`sase.pager._time_band_render_band`, the
meaning and cause rows in :mod:`sase.pager._time_band_render_meaning`,
and the helpers they share in
:mod:`sase.pager._time_band_render_shared`.
"""

from __future__ import annotations

from sase.pager._time_band_render_band import render_time_band


__all__ = [
    "render_time_band",
]
