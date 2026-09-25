"""Key-to-paint probe for the ``:`` Command Line (``SASE_TUI_PERF=1``)."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from typing import Any

from sase.ace.tui.util.perf import is_enabled as tui_perf_enabled
from sase.ace.tui.util.perf import perf_log_path

__all__ = ["schedule_command_line_keystroke_probe"]

#: In-flight appends. The event loop keeps only weak references to tasks, so a
#: task nobody else holds can be collected before it writes its sample.
_PENDING_APPENDS: set[asyncio.Task[None]] = set()


def _command_line_probe_sample(
    keypress_at: float, model_updated_at: float, painted_at: float, indexed: bool
) -> dict[str, object]:
    """Build one command-line key-to-paint perf sample."""
    return {
        "action": "command_line.complete",
        "tab": "command_line",
        "t_keypress": keypress_at,
        "model_ms": round((model_updated_at - keypress_at) * 1000, 3),
        "paint_ms": round((painted_at - keypress_at) * 1000, 3),
        "indexed": indexed,
    }


def _append_command_line_probe(sample: dict[str, object]) -> None:
    """Append a completed probe from a worker, never from the UI thread."""
    if not tui_perf_enabled():
        return
    try:
        path = perf_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(sample) + "\n")
    except OSError:
        # Probe output is diagnostic only: a read-only or full disk must never
        # affect typing.
        pass


def schedule_command_line_keystroke_probe(
    call_after_refresh: Callable[[Callable[[], None]], Any],
    keypress_at: float,
    indexed: bool,
) -> None:
    """Schedule a key-to-popup-paint sample when ``SASE_TUI_PERF=1``.

    ``_refresh_completion`` has already rendered by the time it calls this.
    Capturing the finish from ``call_after_refresh`` therefore measures the
    visible popup, not merely synchronous resolver work. *keypress_at* is
    the key-receipt time when the input stamped one. The JSONL append
    goes through ``asyncio.to_thread`` so this diagnostic never puts disk
    I/O on the input event path.
    """
    if not tui_perf_enabled():
        return
    model_updated_at = time.perf_counter()

    def _after_paint() -> None:
        sample = _command_line_probe_sample(
            keypress_at, model_updated_at, time.perf_counter(), indexed
        )
        try:
            task = asyncio.get_running_loop().create_task(
                asyncio.to_thread(_append_command_line_probe, sample)
            )
        except RuntimeError:  # teardown has no live loop.
            return
        _PENDING_APPENDS.add(task)
        task.add_done_callback(_PENDING_APPENDS.discard)

    try:
        call_after_refresh(_after_paint)
    except Exception:  # noqa: BLE001 - an unmounted panel cannot paint.
        pass
