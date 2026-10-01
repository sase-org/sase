"""Time-axis history for SASE memory and instruction files.

This package owns the Python side of the ``memory history`` feature
(epic design ``plan:202609/memory_history.md`` §5.1): scope assembly,
the thread-safe query service, the shared visual vocabulary, text
rendering, and the ``sase memory history`` command. Lineage,
classification, cause attribution, snapshots, and diffing stay in
``sase-core`` behind :mod:`sase.core.memory_history_facade`.
"""

from __future__ import annotations

from sase.memory.history.pager_provider import (
    MemoryHistoryProvider,
    build_history_document,
)

__all__: list[str] = [
    "MemoryHistoryProvider",
    "build_history_document",
]
