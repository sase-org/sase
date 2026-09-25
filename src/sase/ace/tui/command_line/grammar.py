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

__all__ = [
    "CompletionSpecCacheError",
    "command_line_grammar_for",
    "ensure_command_line_grammar_loaded",
    "is_command_line_grammar_pending",
    "resolve_command_line",
]


def command_line_grammar_for(app: Any) -> Any | None:
    """Return the app-held grammar handle, or ``None`` until it lands."""
    return getattr(app, _COMMAND_LINE_GRAMMAR_ATTR, None)


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


def ensure_command_line_grammar_loaded(
    app: Any,
    *,
    on_ready: Callable[[], None] | None = None,
) -> bool:
    """Start the grammar loader worker unless it already ran.

    Returns True when the handle is already ready. Otherwise marks the
    load pending, fans out to a thread worker, stores the handle on the
    app, and invokes *on_ready* on the app loop when done. Safe to call on every
    panel open; only the first call does any work.
    """
    if command_line_grammar_for(app) is not None:
        return True
    if on_ready is not None:
        callbacks = getattr(app, _COMMAND_LINE_GRAMMAR_READY_CALLBACKS_ATTR, None)
        if callbacks is None:
            callbacks = []
            setattr(app, _COMMAND_LINE_GRAMMAR_READY_CALLBACKS_ATTR, callbacks)
        callbacks.append(on_ready)
    if is_command_line_grammar_pending(app):
        return False
    setattr(app, _COMMAND_LINE_GRAMMAR_LOADING_ATTR, True)
    setattr(app, _COMMAND_LINE_GRAMMAR_ERROR_ATTR, None)

    async def _load() -> None:
        try:
            handle = await asyncio.to_thread(_load_command_line_grammar_sync)
        except CompletionSpecCacheError as error:
            setattr(app, _COMMAND_LINE_GRAMMAR_ERROR_ATTR, str(error))
            log.warning("command-line grammar unavailable: %s", error)
        except Exception as error:  # noqa: BLE001 - load failure is advisory.
            setattr(app, _COMMAND_LINE_GRAMMAR_ERROR_ATTR, str(error))
            log.warning("command-line grammar failed to load: %s", error)
        else:
            setattr(app, _COMMAND_LINE_GRAMMAR_ATTR, handle)
            setattr(app, _COMMAND_LINE_GRAMMAR_ERROR_ATTR, None)
        finally:
            setattr(app, _COMMAND_LINE_GRAMMAR_LOADING_ATTR, False)
        callbacks = getattr(app, _COMMAND_LINE_GRAMMAR_READY_CALLBACKS_ATTR, ())
        setattr(app, _COMMAND_LINE_GRAMMAR_READY_CALLBACKS_ATTR, [])
        for callback in callbacks:
            try:
                callback()
            except Exception:  # noqa: BLE001 - refresh is best effort.
                log.debug("command-line grammar on_ready failed", exc_info=True)

    run_worker = getattr(app, "run_worker", None)
    if callable(run_worker):
        run_worker(_load(), exclusive=False)
    else:  # pragma: no cover - production apps always have run_worker.
        asyncio.ensure_future(_load())
    return False


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
