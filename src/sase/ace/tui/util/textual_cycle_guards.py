"""Feature-probed workarounds for Textual caches that store their owner.

Textual ``Strip.divide`` caches ``[self]`` when the only cut is the strip's
own cell length, and ``Strip.crop_extend`` caches ``self`` when the crop is
the full width. Each creates a cycle (Strip → FIFOCache → dict → … → Strip)
that only a generational collection can free. The census-idle-r4 baseline
showed that path as most of the idle TUI's cyclic garbage by count.

Guards are feature-probed against the unpatched methods: if Textual has
fixed the cycle, or the private cache attribute is gone, install is a
no-op. Wrappers are idempotent and keep the original signature and return
type. Callers of ``divide`` get a fresh ``[self]`` list and never a cached
one, which is safe because the compositor iterates the result without
mutating it or comparing the list by identity.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from functools import wraps
from typing import Any

from rich.segment import Segment
from rich.style import Style
from textual.strip import Strip

log = logging.getLogger(__name__)

_UNPATCHED_DIVIDE = Strip.divide
_UNPATCHED_CROP_EXTEND = Strip.crop_extend
_DIVIDE_DECIDED = False
_CROP_EXTEND_DECIDED = False

__all__ = ["install_textual_cycle_guards"]


def _cache_holds_owner(cache: Any, owner: object, key: object) -> bool:
    """Return True when *cache* stores *owner* (or a list containing it)."""
    if cache is None:
        return False
    getter = getattr(cache, "get", None)
    if getter is None:
        return False
    try:
        cached = getter(key)
    except Exception:
        return False
    if cached is owner:
        return True
    if isinstance(cached, list):
        return any(item is owner for item in cached)
    return False


def _probe_strip_divide_self_cycle() -> bool:
    """Return True when unpatched ``Strip.divide`` caches ``[self]``."""
    if not hasattr(Strip, "divide"):
        return False
    strip = Strip([Segment("probe")], 5)
    cache = getattr(strip, "_divide_cache", None)
    if cache is None:
        return False
    try:
        _UNPATCHED_DIVIDE(strip, [strip.cell_length])
        return _cache_holds_owner(cache, strip, (strip.cell_length,))
    except Exception:
        return False
    finally:
        try:
            cache.clear()
        except Exception:
            pass


def _probe_strip_crop_extend_self_cycle() -> bool:
    """Return True when unpatched ``Strip.crop_extend`` caches ``self``."""
    if not hasattr(Strip, "crop_extend"):
        return False
    strip = Strip([Segment("probe")], 5)
    cache = getattr(strip, "_crop_extend_cache", None)
    if cache is None:
        return False
    cell_length = strip.cell_length
    try:
        _UNPATCHED_CROP_EXTEND(strip, 0, cell_length, None)
        return _cache_holds_owner(cache, strip, (0, cell_length, None))
    except Exception:
        return False
    finally:
        try:
            cache.clear()
        except Exception:
            pass


@wraps(_UNPATCHED_DIVIDE)
def _divide_without_owner_cache(self: Strip, cuts: Iterable[int]) -> Sequence[Strip]:
    """Return a fresh ``[self]`` for a full-width cut; otherwise delegate."""
    cuts_list = list(cuts)
    cell_length = self.cell_length
    filtered = [cut for cut in cuts_list if cut <= cell_length]
    if filtered == [cell_length]:
        return [self]
    return _UNPATCHED_DIVIDE(self, cuts_list)


@wraps(_UNPATCHED_CROP_EXTEND)
def _crop_extend_without_owner_cache(
    self: Strip, start: int, end: int, style: Style | None
) -> Strip:
    """Return ``self`` for a full-width crop without caching it."""
    if start == 0 and end == self.cell_length:
        return self
    return _UNPATCHED_CROP_EXTEND(self, start, end, style)


_divide_without_owner_cache._sase_cycle_guard = True  # type: ignore[attr-defined]
_crop_extend_without_owner_cache._sase_cycle_guard = True  # type: ignore[attr-defined]


def _already_guarded(current: object, wrapper: object) -> bool:
    return current is wrapper or bool(getattr(current, "_sase_cycle_guard", False))


def install_textual_cycle_guards() -> None:
    """Install feature-probed Strip self-cycle guards exactly once.

    Safe to call repeatedly. Never raises: a probe or patch failure leaves
    Textual methods unchanged so TUI import cannot fail because of this.
    """
    global _DIVIDE_DECIDED, _CROP_EXTEND_DECIDED
    try:
        if not _DIVIDE_DECIDED:
            if not _already_guarded(Strip.divide, _divide_without_owner_cache):
                if _probe_strip_divide_self_cycle():
                    Strip.divide = _divide_without_owner_cache  # type: ignore[method-assign]
            _DIVIDE_DECIDED = True
        if not _CROP_EXTEND_DECIDED:
            if not _already_guarded(
                Strip.crop_extend, _crop_extend_without_owner_cache
            ):
                if _probe_strip_crop_extend_self_cycle():
                    Strip.crop_extend = (  # type: ignore[method-assign]
                        _crop_extend_without_owner_cache
                    )
            _CROP_EXTEND_DECIDED = True
    except Exception:
        log.exception("textual cycle guards failed to install")
