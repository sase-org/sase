"""Python facade for the Rust-backed agent/bead touch index.

The reduction itself lives in ``sase-core`` (``bead/touch_index.rs``): it
reduces per-bead event streams into actor-keyed touch rows, keeps a
signature-cached index at ``~/.sase/projects/<key>/agent_bead_touches.json``,
and answers read-only queries from that file. The implementation lives in
the sibling modules below; this facade only re-exports the public names so
the original import path keeps working:

- :mod:`sase.core.bead_touch_index_models` — wire-stable records.
- :mod:`sase.core.bead_touch_index_store` — path resolution and refresh.
- :mod:`sase.core.bead_touch_index_query` — queries and agent matching.
- :mod:`sase.core.bead_touch_index_fold` — per-bead folding.
"""

from __future__ import annotations

from sase.core.bead_touch_index_fold import (
    canonical_bead_touch_id,
    fold_read_reasons,
    fold_touches_per_bead,
    prefer_bead_touch_close,
)
from sase.core.bead_touch_index_models import (
    TOUCH_INDEX_FILENAME,
    BeadNotePreview,
    BeadTouch,
    BeadTouchClose,
    BeadTouchIndexStatus,
    BeadTouchQuery,
    BeadTouchRefresh,
    FoldedBeadTouch,
)
from sase.core.bead_touch_index_query import (
    merge_view_touches,
    query_touches_for_agent,
    query_touch_index,
    touch_matches_agent,
)
from sase.core.bead_touch_index_store import (
    refresh_touch_index_best_effort,
    resolve_touch_index_project,
    touch_index_path,
    touch_index_status,
)

__all__ = [
    "TOUCH_INDEX_FILENAME",
    "BeadNotePreview",
    "BeadTouch",
    "BeadTouchClose",
    "BeadTouchIndexStatus",
    "BeadTouchQuery",
    "BeadTouchRefresh",
    "FoldedBeadTouch",
    "canonical_bead_touch_id",
    "fold_read_reasons",
    "fold_touches_per_bead",
    "merge_view_touches",
    "prefer_bead_touch_close",
    "query_touches_for_agent",
    "query_touch_index",
    "refresh_touch_index_best_effort",
    "resolve_touch_index_project",
    "touch_index_path",
    "touch_index_status",
    "touch_matches_agent",
]
