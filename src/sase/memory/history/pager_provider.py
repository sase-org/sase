"""Memory history pager provider backed by ``HistoryService``.

Recognizes canonical and legacy project memory, web descriptors and
strands, root/subdirectory AGENTS.md and shims, chezmoi source templates,
and deployed home files from subject/owner provenance rather than title
alone. All git, lineage, selector, and diff semantics stay in
``sase-core``; this module only normalizes wire results into pager
presentation records.

This module is a facade preserving the original public import path.
Provider logic lives in :mod:`sase.memory.history.pager_provider_core`;
the document builder lives in
:mod:`sase.memory.history.pager_provider_document`; timeline helpers live
in :mod:`sase.memory.history.pager_provider_timelines`.
"""

from __future__ import annotations

from sase.memory.history.pager_provider_document import (
    build_history_document as build_history_document,
)
from sase.memory.history.pager_provider_document import (
    selector_to_core_selector as selector_to_core_selector,
)
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
from sase.memory.history.pager_provider_core import (
    memory_history_provider_factory as memory_history_provider_factory,
)

__all__ = [
    "build_history_document",
    "dirty_now_from_timeline",
    "history_marks_from_comparison",
    "is_deleted_row",
    "memory_history_provider_factory",
    "newest_committed_row",
    "selector_to_core_selector",
    "visible_ordinals_for_timeline",
]
