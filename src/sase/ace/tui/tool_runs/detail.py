"""Per-block run-detail loader for the ``⚒ Runs`` card (plan §3.5.3).

A worker load runs for the visible blocks only: one
``tool_run_detail`` call plus the bounded log tail via the shared
``tool_run_log_tail`` helper in the same worker call. Results go in an
LRU (32 entries) keyed by ``(run_id, settled_ts)`` — settled runs are
effectively immutable — or ``(run_id, "live", store token)`` while
live. The tail is always read at FULL depth; the renderer slices per
detail level. Nothing here runs on a render or keystroke path.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any
from collections.abc import Callable

from sase.core.tool_run import ToolRunDetail, tool_run_detail

from .blocks import FULL_TAIL_LINES

#: Detail LRU capacity (plan §3.5.3).
DETAIL_LRU_MAX = 32

_detail_lock = threading.Lock()
_detail_lru: OrderedDict[tuple[str, ...], LoadedToolRunDetail] = OrderedDict()


@dataclass(frozen=True)
class LoadedToolRunDetail:
    """One loaded block: the detail plus its bounded tail."""

    run_id: str
    detail: ToolRunDetail
    tail: Any | None = None
    live: bool = False


def _detail_lru_key(
    run_id: str,
    brief: Any | None,
    store_token: Any | None,
) -> tuple[str, ...]:
    """Return the LRU key for one block (plan §3.5.3).

    Settled runs key on ``(run_id, settled_ts)``; live runs key on
    ``(run_id, "live", store token)`` so a glance drift refetches them.
    """

    clean = str(run_id or "")
    state = str(getattr(brief, "state", "") or "") if brief is not None else ""
    if state in ("created", "running"):
        return (clean, "live", str(store_token))
    settled = getattr(brief, "settled_ts", None) if brief is not None else None
    try:
        settled_part = str(int(settled)) if settled is not None else "settled"
    except (TypeError, ValueError):
        settled_part = "settled"
    return (clean, settled_part)


def cached_tool_run_detail(
    run_id: str,
    brief: Any | None = None,
    store_token: Any | None = None,
) -> LoadedToolRunDetail | None:
    """Return the cached detail for one block, if any (never raises)."""

    try:
        key = _detail_lru_key(run_id, brief, store_token)
    except Exception:
        return None
    try:
        with _detail_lock:
            hit = _detail_lru.get(key)
            if hit is not None:
                _detail_lru.move_to_end(key)
            return hit
    except Exception:
        return None


def _store_tool_run_detail(key: tuple[str, ...], loaded: LoadedToolRunDetail) -> None:
    """Store one loaded block, evicting the oldest beyond capacity."""

    try:
        with _detail_lock:
            _detail_lru[key] = loaded
            _detail_lru.move_to_end(key)
            while len(_detail_lru) > DETAIL_LRU_MAX:
                _detail_lru.popitem(last=False)
    except Exception:
        pass


def load_tool_run_detail_blocking(
    run_id: str,
    brief: Any | None = None,
    store_token: Any | None = None,
    *,
    is_current: Callable[[], bool] | None = None,
) -> LoadedToolRunDetail | None:
    """Load one block's detail plus tail; the tail read is bounded.

    Hits the LRU first (a settled hit never re-reads). Misses call
    ``tool_run_detail`` and then the shared ``tool_run_log_tail``
    helper in this same worker call. Returns None when the store is
    missing, the binding is stale, or ``is_current`` rejects the
    result — the caller then renders the brief-only block with an
    honest-absence line.
    """

    clean = str(run_id or "")
    if not clean:
        return None
    try:
        key = _detail_lru_key(clean, brief, store_token)
    except Exception:
        return None
    try:
        with _detail_lock:
            hit = _detail_lru.get(key)
            if hit is not None:
                _detail_lru.move_to_end(key)
                return hit
    except Exception:
        pass
    try:
        detail = tool_run_detail(clean)
    except Exception:
        return None
    if is_current is not None:
        try:
            if not is_current():
                return None
        except Exception:
            return None
    tail: Any | None = None
    try:
        from sase.tool.logs import log_policy, tool_run_log_tail

        try:
            max_bytes = int(log_policy().get("run_log_max_bytes", 256 * 1024))
        except Exception:
            max_bytes = 256 * 1024
        metadata = detail.logs.to_tail_metadata()
        if bool(getattr(detail, "detail_pruned", False)):
            metadata = {**metadata, "detail_pruned": True}
        tail = tool_run_log_tail(
            clean,
            metadata,
            getattr(brief, "owner_kind", None),
            getattr(brief, "owner_id", None),
            FULL_TAIL_LINES,
            max_bytes,
        )
    except Exception:
        tail = None
    state = str(getattr(brief, "state", "") or "")
    loaded = LoadedToolRunDetail(
        run_id=clean,
        detail=detail,
        tail=tail,
        live=state in ("created", "running"),
    )
    _store_tool_run_detail(key, loaded)
    return loaded


__all__ = [
    "DETAIL_LRU_MAX",
    "LoadedToolRunDetail",
    "cached_tool_run_detail",
    "load_tool_run_detail_blocking",
]
