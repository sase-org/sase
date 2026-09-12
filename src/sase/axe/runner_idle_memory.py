"""Hand a parked runner's bootstrap peak back to the operating system.

A runner finishes its whole bootstrap -- directive extraction, prompt
assembly, xprompt expansion -- before it learns whether it has to wait at all.
That work allocates heavily and then drops nearly all of it, but neither
CPython's arena allocator nor glibc's returns the freed pages on its own: a
runner that peaks near half a gigabyte keeps that resident for as long as it
then sits in a dependency or runner-slot wait. One parked runner is
unremarkable; several dozen of them on one host is tens of gigabytes of
resident memory belonging to agents that are doing nothing, which is enough to
push the host into swap and stall the agents that *are* running.

``gc.collect()`` alone does not fix this, because the objects are already
unreachable -- it is the allocator, not the collector, that is holding on.
``malloc_trim`` is what actually releases the arenas, so both are needed.

Trimming is pure memory hygiene: it happens at the head of a wait and on the
wait's own coarse polling cadence, and changes no barrier semantics.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import gc
import sys
import threading

# How often a long-lived wait loop re-trims. Waits poll on a seconds-scale
# interval, which is far too hot for a heap walk; the allocating work inside a
# wait (dependency fallback resolution, axe healing) runs on a minute scale, so
# this cadence tracks the garbage rather than the polling.
IDLE_TRIM_INTERVAL_SECONDS = 60.0

_RESOLVE_LOCK = threading.Lock()
_malloc_trim: ctypes._NamedFuncPointer | None = None
_resolved = False


def _resolve_malloc_trim() -> ctypes._NamedFuncPointer | None:
    """Resolve glibc's ``malloc_trim``, or ``None`` where there is no such symbol.

    Resolution is cached because a wait loop calls this repeatedly, and loading
    libc on every poll would cost more than the trim it is arranging.
    """
    global _malloc_trim, _resolved

    if _resolved:
        return _malloc_trim
    with _RESOLVE_LOCK:
        if _resolved:
            return _malloc_trim
        resolved: ctypes._NamedFuncPointer | None = None
        # macOS and musl have no malloc_trim; only glibc is worth probing.
        if sys.platform.startswith("linux"):
            try:
                libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6")
                resolved = libc.malloc_trim
                resolved.argtypes = [ctypes.c_size_t]
                resolved.restype = ctypes.c_int
            except (OSError, AttributeError):
                resolved = None
        _malloc_trim = resolved
        _resolved = True
        return _malloc_trim


def release_idle_memory() -> bool:
    """Collect garbage and return freed heap to the OS; report whether any moved.

    Never raises. A runner that cannot trim -- a non-glibc host, a libc without
    the symbol -- must still wait correctly, so every failure degrades to
    returning ``False`` and leaving the process exactly as it was.
    """
    gc.collect()
    trim = _resolve_malloc_trim()
    if trim is None:
        return False
    try:
        return bool(trim(0))
    except OSError:
        return False
