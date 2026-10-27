"""Key-to-paint perf instrumentation for sase's TUI.

Phase 1 of sdd/tales/202604/instant_jk_navigation.md (bead sase-u.1). Captures
three timestamps for every j/k navigation, plus the prompt ``<space>`` and
``<ctrl+n/p>`` keys (epic sase-1ex, phase key-perf-harness):

- ``t_keypress``     -- action handler entry (monotonic ``perf_counter``)
- ``t_model_updated`` -- after ``current_idx`` mutation
- ``t_painted``      -- after the next Textual refresh cycle

Each sample is appended as JSON to ``~/.sase/perf/tui_jk.jsonl`` (override
with ``SASE_TUI_PERF_PATH``) and retained in a rolling in-memory window so
``JKPerfTimer.summary()`` can report p50/p95/max for each scenario.

The instrumentation is a no-op unless ``SASE_TUI_PERF=1`` is set in the
environment when ``AceApp`` initializes.

Attribution (epic sase-1nf.14.1, phase interaction-evidence): every sample
carries ``app_instance_id``, ``pid``, a wall-clock timestamp paired with
the monotonic action time, a cumulative ``dropped_total`` counter, and a
provenance snapshot (sase version, source revision, Python version)
captured once at bind time -- never rediscovered per key. Overwritten
in-flight samples increment ``dropped_total`` so a sparse distribution is
not mistaken for all input. The sample log keeps one row kind only (the
existing freeze-report consumers read every row as a sample); it rotates to
a single ``.1`` generation past ``max_bytes``.

Prompt/modal activity (same phase): :class:`PromptActivityTracker` emits an
initial activity state plus open/close transitions for prompt-active and
modal text-entry activity, with the same instance/time attribution, through
the telemetry writer (:func:`_emit_prompt_activity` into ``tui_stalls.jsonl``,
which the freeze report already joins per instance). It never logs prompt
contents. Durations are reconstructed from state transitions; intervals
before a known starting state are explicitly ``unknown``. Tracking is
active only when perf capture is enabled, with bounded in-memory storage
(the durable rotation is the stalls log's).
"""

from __future__ import annotations

import logging
import os
import platform
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from statistics import median
from typing import Any

from .perf_writer import PerfWriter

from sase.core.paths import sase_subdir
from sase.logs._bounded import append_jsonl_record

log = logging.getLogger(__name__)

ENV_FLAG = "SASE_TUI_PERF"
ENV_PATH = "SASE_TUI_PERF_PATH"
DEFAULT_WINDOW = 200
DEFAULT_MAX_BYTES = 2 * 1024 * 1024
ACTIVITY_WINDOW = 512


def is_enabled() -> bool:
    """Return True when ``SASE_TUI_PERF=1`` is set in the environment."""
    return os.environ.get(ENV_FLAG) == "1"


def perf_log_path() -> Path:
    """Return the JSONL path for perf samples (env-overridable)."""
    override = os.environ.get(ENV_PATH)
    if override:
        return Path(override)
    return sase_subdir("perf") / "tui_jk.jsonl"


def _provenance_snapshot() -> dict[str, Any]:
    """Capture source/runtime provenance once (never per keypress).

    All three lookups are cheap and cached upstream: ``sase.__version__``
    is I/O-free, the imported revision is snapshotted at import, and the
    Python version is a runtime constant. Anything unavailable stays
    ``None`` instead of raising.
    """
    try:
        import sase

        sase_version: str | None = getattr(sase, "__version__", None)
    except Exception:  # noqa: BLE001 - provenance must never break capture.
        sase_version = None
    try:
        from sase.ace.tui.util.imported_revision import imported_source_revision

        source_revision: str | None = imported_source_revision()
    except Exception:  # noqa: BLE001 - provenance must never break capture.
        source_revision = None
    try:
        python_version: str | None = platform.python_version()
    except Exception:  # noqa: BLE001 - provenance must never break capture.
        python_version = None
    return {
        "sase_version": sase_version,
        "source_revision": source_revision,
        "python_version": python_version,
    }


class JKPerfTimer:
    """Per-app perf state. Records key-to-paint latencies for j/k actions.

    All times are captured with ``time.perf_counter()``. The timer holds a
    single in-flight sample at a time -- if a new ``begin()`` arrives before
    ``mark_painted()`` finishes the previous sample, the previous one is
    discarded and counted in ``dropped_samples``. This is the right behavior
    for j/k navigation, where the user cares about the latency of the *most
    recent* keystroke, not stacked work.
    """

    def __init__(
        self,
        *,
        window: int = DEFAULT_WINDOW,
        log_path: Path | None = None,
        app_instance_id: str | None = None,
        pid: int | None = None,
        provenance: dict[str, Any] | None = None,
        max_bytes: int = DEFAULT_MAX_BYTES,
        writer: PerfWriter | None = None,
    ) -> None:
        self._writer = writer
        self.window = window
        self.log_path = log_path if log_path is not None else perf_log_path()
        self.app_instance_id = app_instance_id
        self.pid = pid if pid is not None else os.getpid()
        self.provenance = (
            dict(provenance) if provenance is not None else _provenance_snapshot()
        )
        self.max_bytes = max_bytes
        self._samples: deque[dict[str, Any]] = deque(maxlen=window)
        self._inflight: dict[str, Any] | None = None
        self._dropped = 0
        self._dropped_by_tab: dict[str, int] = {}

    def bind(
        self,
        app_instance_id: str | None,
        provenance: dict[str, Any] | None = None,
    ) -> None:
        """Attach the app instance ID minted at app construction.

        The timer is built in ``AceApp.__init__`` before the instance ID
        exists; the app calls this once the ID is minted (a re-exec mints a
        new ID, which defines a new instance). Provenance defaults to a
        fresh one-time snapshot.
        """
        self.app_instance_id = app_instance_id
        self.provenance = (
            dict(provenance) if provenance is not None else _provenance_snapshot()
        )

    @property
    def dropped_samples(self) -> int:
        """Samples discarded because a newer keypress overwrote them."""
        return self._dropped

    def begin(self, action: str, tab: str) -> None:
        """Record the start of a navigation action (``t_keypress``)."""
        if self._inflight is not None:
            self._dropped += 1
            dropped_tab = self._inflight["tab"]
            self._dropped_by_tab[dropped_tab] = (
                self._dropped_by_tab.get(dropped_tab, 0) + 1
            )
        self._inflight = {
            "action": action,
            "tab": tab,
            "t_keypress": time.perf_counter(),
            "t_wall": time.time(),
        }

    def mark_model_updated(self) -> None:
        """Record the time the in-memory model finished mutating."""
        if self._inflight is None:
            return
        self._inflight["t_model_updated"] = time.perf_counter()

    def mark_painted(self) -> None:
        """Record the next-paint time, finalize the sample, and append it."""
        if self._inflight is None:
            return
        sample = self._inflight
        self._inflight = None
        sample["t_painted"] = time.perf_counter()
        sample["model_ms"] = (
            sample.get("t_model_updated", sample["t_painted"]) - sample["t_keypress"]
        ) * 1000.0
        sample["paint_ms"] = (sample["t_painted"] - sample["t_keypress"]) * 1000.0
        self._samples.append(sample)
        self._write(sample)

    @property
    def inflight_action(self) -> str | None:
        """Return the in-flight sample's action, or ``None`` when idle."""
        if self._inflight is None:
            return None
        action = self._inflight.get("action")
        return action if isinstance(action, str) else None

    def discard(self) -> None:
        """Drop the in-flight sample (no-op when nothing is pending)."""
        self._inflight = None

    def samples(self) -> list[dict[str, Any]]:
        """Return a snapshot of the rolling window (most recent last)."""
        return list(self._samples)

    def summary(self) -> dict[str, dict[str, float]]:
        """Return p50/p95/max paint_ms grouped by action, for the window."""
        by_action: dict[str, list[float]] = {}
        for s in self._samples:
            by_action.setdefault(s["action"], []).append(float(s["paint_ms"]))
        out: dict[str, dict[str, float]] = {}
        for action, vals in by_action.items():
            vs = sorted(vals)
            n = len(vs)
            p95_idx = max(0, int(round(0.95 * (n - 1))))
            out[action] = {
                "n": float(n),
                "p50": float(median(vs)),
                "p95": vs[p95_idx],
                "max": vs[-1],
            }
        return out

    def _sample_row(self, sample: dict[str, Any]) -> dict[str, Any]:
        row = {
            "action": sample["action"],
            "tab": sample["tab"],
            "t_keypress": sample["t_keypress"],
            "model_ms": sample["model_ms"],
            "paint_ms": sample["paint_ms"],
        }
        row["app_instance_id"] = self.app_instance_id
        row["pid"] = self.pid
        row["t_wall"] = sample.get("t_wall")
        row["dropped_total"] = self._dropped
        row["dropped_by_tab"] = dict(self._dropped_by_tab)
        row.update(self.provenance)
        return row

    def _write(self, sample: dict[str, Any]) -> None:
        row = self._sample_row(sample)
        if self._writer is None:
            self._append_row(row)
        elif not self._writer.submit(self._append_row, row):
            self._dropped += 1
            tab = sample["tab"]
            self._dropped_by_tab[tab] = self._dropped_by_tab.get(tab, 0) + 1

    def _append_row(self, row: dict[str, Any]) -> None:
        try:
            # Shared bounded-log locking coordinates multiple captured TUIs.
            # AceApp calls this only on the perf writer, never on the UI loop.
            append_jsonl_record(self.log_path, row, max_bytes=self.max_bytes)
        except OSError as e:
            log.debug("perf log write failed: %s", e)


def _emit_prompt_activity(row: dict[str, Any]) -> None:
    """Write one activity row through the telemetry writer.

    Activity rows share ``tui_stalls.jsonl`` with the GC pause/heartbeat
    rows so the freeze report can join them per instance. The ace testing
    harness replaces this sender with a no-op, mirroring the GC telemetry
    install patch: a pytest host runs many app instances and must not touch
    the real stalls log.
    """
    try:
        from sase.logs import log_tui_stall
    except Exception:  # noqa: BLE001 - telemetry must never break capture.
        return
    try:
        log_tui_stall(dict(row))
    except Exception as e:  # noqa: BLE001 - telemetry must never break input.
        log.debug("prompt activity emit failed: %s", e)


class PromptActivityTracker:
    """Prompt-active and modal text-entry state transitions for one instance.

    Emits an initial activity state plus open/close transitions with the
    same instance/time attribution as perf samples, through the telemetry
    writer (:func:`_emit_prompt_activity` into ``tui_stalls.jsonl``, which
    the freeze report already joins per instance). Never logs prompt
    contents -- rows carry only state names, screen names, and timestamps.

    Durations are reconstructed from transitions; spans before a known
    starting state are explicitly ``unknown``. The tracker holds a bounded
    deque of recent transitions; the durable rotation is the stalls log's.
    Only drive it when perf capture is enabled. Pass a custom *emit* sink
    in tests to avoid touching the real stalls log.
    """

    def __init__(
        self,
        *,
        app_instance_id: str | None = None,
        pid: int | None = None,
        emit: Callable[[dict[str, Any]], None] | None = None,
        writer: PerfWriter | None = None,
    ) -> None:
        self.app_instance_id = app_instance_id
        self.pid = pid if pid is not None else os.getpid()
        self._emit = emit
        self._writer = writer
        self._sequence = -1
        self._snapshot: dict[str, Any] = {}
        self._transitions: deque[dict[str, Any]] = deque(maxlen=ACTIVITY_WINDOW)
        self._prompt_open = False
        self._modal: tuple[str, bool | None] | None = None
        self._started = False

    def bind(self, app_instance_id: str | None) -> None:
        """Attach the app instance ID minted at app construction."""
        self.app_instance_id = app_instance_id

    def start(self, *, prompt_open: bool | None = None) -> None:
        """Emit the initial activity state row.

        ``prompt_open`` seeds the starting state when the caller knows it;
        ``None`` records an explicitly unknown start so later spans are not
        misattributed.
        """
        if self._started:
            return
        self._started = True
        if prompt_open is not None:
            self._prompt_open = bool(prompt_open)
            state = "prompt_active" if self._prompt_open else "prompt_idle"
        else:
            state = "unknown"
        self._record("initial", state, screen=None, text_entry=None)

    def note_prompt_opened(self) -> None:
        """Record the prompt text entry gaining focus."""
        if self._prompt_open:
            return
        self._prompt_open = True
        self._record(
            "prompt_opened", self._current_state(), screen=None, text_entry=True
        )

    def note_prompt_closed(self) -> None:
        """Record the prompt text entry losing focus."""
        if not self._prompt_open:
            return
        self._prompt_open = False
        self._record(
            "prompt_closed", self._current_state(), screen=None, text_entry=True
        )

    def _current_state(self) -> str:
        if self._modal is not None:
            entry = self._modal[1]
            # Until composition there is no mounted text entry on this screen.
            return "modal_active" if entry else "modal_open"
        return "prompt_active" if self._prompt_open else "prompt_idle"

    def set_modal(self, screen: str | None, *, text_entry: bool | None) -> None:
        """Snapshot the visible modal after a screen change or composition."""
        modal = (screen, text_entry) if screen is not None else None
        if modal == self._modal:
            return
        self._modal = modal
        self._record(
            "screen_changed",
            self._current_state(),
            screen=screen,
            text_entry=text_entry,
        )

    def checkpoint(self) -> dict[str, Any]:
        """Heartbeat witness for the latest transition, including a lost tail."""
        return {
            "prompt_activity": {
                **self._snapshot,
                "transition": "checkpoint",
                "t_mono": time.perf_counter(),
                "t_wall": time.time(),
            }
        }

    @property
    def transitions(self) -> list[dict[str, Any]]:
        """Bounded in-memory snapshot of recent transitions (oldest first)."""
        return list(self._transitions)

    def _record(
        self,
        transition: str,
        state: str,
        *,
        screen: str | None,
        text_entry: bool | None,
    ) -> None:
        self._sequence += 1
        row = {
            "sequence": self._sequence,
            "event": "prompt_activity",
            "transition": transition,
            "state": state,
            "screen": screen,
            "text_entry": text_entry,
            "app_instance_id": self.app_instance_id,
            "pid": self.pid,
            "t_mono": time.perf_counter(),
            "t_wall": time.time(),
        }
        self._snapshot = row
        self._transitions.append(dict(row))
        sink = self._emit or _emit_prompt_activity
        try:
            if self._writer is None:
                sink(dict(row))
            else:
                self._writer.submit(sink, dict(row))
        except Exception as e:  # noqa: BLE001 - telemetry must never break input.
            log.debug("prompt activity emit failed: %s", e)
