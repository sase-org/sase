"""Idle grammar loading for the ``:`` Command Line panel.

The frozen ``CommandLineGrammar`` handle is built once per app session in a
thread worker: :func:`ensure_command_line_spec` builds (or reuses) the
on-disk spec in a subprocess, then :func:`load_command_line_grammar` parses
it into the Rust handle. The keystroke path only ever reads the app-held
handle, so typing never spawns a process or touches the disk.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from collections.abc import Callable

from sase.completion.command_line_grammar import (
    CommandLineGrammar,
    LineContext,
    load_command_line_grammar,
)
from sase.completion.command_line_spec import (
    CompletionSpecCacheError,
    current_command_line_spec_key,
    ensure_command_line_spec,
)

log = logging.getLogger(__name__)

#: App attribute holding the ready grammar handle (or ``None``).
_COMMAND_LINE_GRAMMAR_ATTR = "_command_line_grammar"
#: App attribute set while the loader worker is in flight.
_COMMAND_LINE_GRAMMAR_LOADING_ATTR = "_command_line_grammar_loading"
#: App attribute holding the last loader error message (or ``None``).
_COMMAND_LINE_GRAMMAR_ERROR_ATTR = "_command_line_grammar_error"
#: App attribute holding every screen callback awaiting the current load.
_COMMAND_LINE_GRAMMAR_READY_CALLBACKS_ATTR = "_command_line_grammar_ready_callbacks"
#: App attribute holding the spec key the ready handle was built from.
_COMMAND_LINE_GRAMMAR_KEY_ATTR = "_command_line_grammar_key"
#: App attribute set while a background freshness recheck is in flight.
_COMMAND_LINE_GRAMMAR_RECHECK_ATTR = "_command_line_grammar_rechecking"

__all__ = [
    "CompletionSpecCacheError",
    "command_line_grammar_for",
    "command_line_grammar_spec_key_for",
    "ensure_command_line_grammar_loaded",
    "is_command_line_grammar_pending",
    "resolve_command_line",
]


def command_line_grammar_for(app: Any) -> Any | None:
    """Return the app-held grammar handle, or ``None`` until it lands."""
    return getattr(app, _COMMAND_LINE_GRAMMAR_ATTR, None)


def command_line_grammar_spec_key_for(app: Any) -> str | None:
    """Return the spec key the app-held grammar handle was built from."""
    key = getattr(app, _COMMAND_LINE_GRAMMAR_KEY_ATTR, None)
    return key if isinstance(key, str) else None


def is_command_line_grammar_pending(app: Any) -> bool:
    """Return True while the loader worker is still in flight."""
    return bool(getattr(app, _COMMAND_LINE_GRAMMAR_LOADING_ATTR, False))


def _load_command_line_grammar_sync() -> CommandLineGrammar:
    """Build (or reuse) the spec and load the frozen grammar handle.

    Call only from a worker thread: the spec build shells out to a
    subprocess and parses a ~0.5 MB document. Raises
    :class:`CompletionSpecCacheError` when the spec cannot be built.
    """
    try:
        spec_path = ensure_command_line_spec()
    except CompletionSpecCacheError:
        raise
    except Exception as error:  # noqa: BLE001 - loader errors become messages.
        raise CompletionSpecCacheError(str(error) or type(error).__name__) from error
    return load_command_line_grammar(spec_path)


def _take_grammar_callbacks(app: Any) -> list[Callable[[], None]]:
    """Drain the queued grammar-ready callbacks held on *app*."""
    callbacks = getattr(app, _COMMAND_LINE_GRAMMAR_READY_CALLBACKS_ATTR, ())
    setattr(app, _COMMAND_LINE_GRAMMAR_READY_CALLBACKS_ATTR, [])
    return list(callbacks)


def _invoke_grammar_callbacks(callbacks: list[Callable[[], None]]) -> None:
    """Invoke drained grammar-ready callbacks; refresh is best effort."""
    for callback in callbacks:
        try:
            callback()
        except Exception:  # noqa: BLE001 - refresh is best effort.
            log.debug("command-line grammar on_ready failed", exc_info=True)


def _start_grammar_worker(app: Any, loader: Callable[[], Any]) -> None:
    """Fan *loader* out through the app worker (or the bare event loop)."""
    run_worker = getattr(app, "run_worker", None)
    if callable(run_worker):
        run_worker(loader(), exclusive=False)
    else:  # pragma: no cover - production apps always have run_worker.
        asyncio.ensure_future(loader())


def ensure_command_line_grammar_loaded(
    app: Any,
    *,
    on_ready: Callable[[], None] | None = None,
) -> bool:
    """Start the grammar loader worker unless it already ran.

    Returns True when the handle is already ready. Otherwise marks the
    load pending, fans out to a thread worker, stores the handle on the
    app, and invokes *on_ready* on the app loop when done. Safe to call on every
    panel open: after the first load, each call rechecks the spec key in the
    existing thread worker and reloads the grammar only when the key changed
    (a plugin install, uninstall, or editable source edit), leaving the live
    handle untouched otherwise. The recheck never sets the pending flag, so
    typing and completion keep serving the current handle.
    """
    if on_ready is not None:
        callbacks = getattr(app, _COMMAND_LINE_GRAMMAR_READY_CALLBACKS_ATTR, None)
        if callbacks is None:
            callbacks = []
            setattr(app, _COMMAND_LINE_GRAMMAR_READY_CALLBACKS_ATTR, callbacks)
        callbacks.append(on_ready)
    if command_line_grammar_for(app) is not None:
        if not getattr(app, _COMMAND_LINE_GRAMMAR_RECHECK_ATTR, False):
            setattr(app, _COMMAND_LINE_GRAMMAR_RECHECK_ATTR, True)
            _start_grammar_worker(app, lambda: _recheck_grammar_key(app))
        return True
    if is_command_line_grammar_pending(app):
        return False
    setattr(app, _COMMAND_LINE_GRAMMAR_LOADING_ATTR, True)
    setattr(app, _COMMAND_LINE_GRAMMAR_ERROR_ATTR, None)
    _start_grammar_worker(app, lambda: _load_grammar(app))
    return False


async def _load_grammar(app: Any) -> None:
    """First-load worker: build the spec, load the handle, record its key."""
    try:
        handle = await asyncio.to_thread(_load_command_line_grammar_sync)
    except CompletionSpecCacheError as error:
        setattr(app, _COMMAND_LINE_GRAMMAR_ERROR_ATTR, str(error))
        log.warning("command-line grammar unavailable: %s", error)
    except Exception as error:  # noqa: BLE001 - load failure is advisory.
        setattr(app, _COMMAND_LINE_GRAMMAR_ERROR_ATTR, str(error))
        log.warning("command-line grammar failed to load: %s", error)
    else:
        try:
            key = await asyncio.to_thread(current_command_line_spec_key)
        except Exception as error:  # noqa: BLE001 - key is advisory; recheck heals.
            log.debug("command-line grammar key capture failed: %s", error)
            key = None
        setattr(app, _COMMAND_LINE_GRAMMAR_ATTR, handle)
        if key is not None:
            setattr(app, _COMMAND_LINE_GRAMMAR_KEY_ATTR, key)
        setattr(app, _COMMAND_LINE_GRAMMAR_ERROR_ATTR, None)
    finally:
        setattr(app, _COMMAND_LINE_GRAMMAR_LOADING_ATTR, False)
    _invoke_grammar_callbacks(_take_grammar_callbacks(app))


async def _recheck_grammar_key(app: Any) -> None:
    """Recheck the spec key off-thread; reload the grammar only on change.

    Long-lived TUIs keep their loaded handle across ``:`` opens. Each open
    recomputes the key here (metadata reads and file stats only, never a
    plugin import) and rebuilds only when a plugin change moved it.
    """
    try:
        try:
            key = await asyncio.to_thread(current_command_line_spec_key)
        except Exception as error:  # noqa: BLE001 - recheck is advisory.
            log.debug("command-line grammar key recheck failed: %s", error)
            return
        if key == command_line_grammar_spec_key_for(app):
            _take_grammar_callbacks(app)
            return
        try:
            handle = await asyncio.to_thread(_load_command_line_grammar_sync)
        except CompletionSpecCacheError as error:
            setattr(app, _COMMAND_LINE_GRAMMAR_ERROR_ATTR, str(error))
            log.warning("command-line grammar unavailable: %s", error)
            return
        except Exception as error:  # noqa: BLE001 - reload failure is advisory.
            setattr(app, _COMMAND_LINE_GRAMMAR_ERROR_ATTR, str(error))
            log.warning("command-line grammar failed to reload: %s", error)
            return
        setattr(app, _COMMAND_LINE_GRAMMAR_ATTR, handle)
        setattr(app, _COMMAND_LINE_GRAMMAR_KEY_ATTR, key)
        setattr(app, _COMMAND_LINE_GRAMMAR_ERROR_ATTR, None)
    finally:
        setattr(app, _COMMAND_LINE_GRAMMAR_RECHECK_ATTR, False)
    _invoke_grammar_callbacks(_take_grammar_callbacks(app))


def resolve_command_line(app: Any, line: str, cursor: int) -> LineContext | None:
    """Resolve *line* at *cursor* through the app-held grammar, if ready.

    Synchronous and in memory: the frozen handle, no processes, no locks.
    Returns ``None`` until the loader worker lands.
    """
    handle = command_line_grammar_for(app)
    if handle is None:
        return None
    try:
        return handle.resolve(line, cursor)  # type: ignore[no-any-return]
    except Exception:  # noqa: BLE001 - advisory path never raises.
        log.debug("command-line resolve failed for %r", line, exc_info=True)
        return None
