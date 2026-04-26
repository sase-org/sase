"""Async I/O scheduling helpers for TUI action handlers.

Action handlers that mutate persistent state should:

1. Apply the optimistic in-memory mutation immediately.
2. Refresh the UI immediately so the keystroke feels instant.
3. Hand the disk write to :func:`schedule_persist`, which runs the
   blocking call on a worker via ``asyncio.to_thread``.

If the worker raises, the helper surfaces a toast notification with
``severity="error"`` and invokes the optional ``on_error`` callback so the
handler can roll back the optimistic mutation. On success, the optional
``on_success`` callback runs on the UI thread (Textual already pumps the
awaitable on the event loop).

The helper takes a Textual-app-like object exposing ``notify`` and
``call_later``; we model that with :class:`_AppLike` rather than importing
Textual at module load so unit tests can substitute a plain fake.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any, Protocol

log = logging.getLogger(__name__)


class _AppLike(Protocol):
    """Subset of the Textual ``App`` API used by :func:`schedule_persist`."""

    def notify(  # noqa: D401 — protocol mirrors Textual signature
        self,
        message: str,
        *,
        severity: str = ...,
    ) -> Any: ...

    def call_later(  # noqa: D401 — protocol mirrors Textual signature
        self,
        callback: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any: ...


def schedule_persist[T](
    app: _AppLike,
    persist_fn: Callable[..., T],
    *args: Any,
    error_label: str,
    on_success: Callable[[T], None] | None = None,
    on_error: Callable[[BaseException], None] | None = None,
) -> None:
    """Run a blocking persistence call on a worker without blocking the UI.

    ``persist_fn(*args)`` executes on a worker thread via
    ``asyncio.to_thread``. The caller must have already applied any
    optimistic in-memory mutation. On failure the user sees an error toast
    of the form ``"<error_label> failed: <exc>"`` and ``on_error`` runs so
    the caller can revert state. Both callbacks run on the UI thread.
    """

    async def _runner() -> None:
        try:
            result = await asyncio.to_thread(persist_fn, *args)
        except Exception as exc:
            log.exception("%s failed", error_label)
            try:
                app.notify(f"{error_label} failed: {exc}", severity="error")
            except Exception:
                log.exception("notify() failed while reporting %s error", error_label)
            if on_error is not None:
                try:
                    on_error(exc)
                except Exception:
                    log.exception("%s on_error callback failed", error_label)
            return
        if on_success is not None:
            try:
                on_success(result)
            except Exception:
                log.exception("%s on_success callback failed", error_label)

    app.call_later(_runner)
