"""Key-to-paint perf instrumentation for the ace TUI.

Phase 1 of sdd/tales/202604/instant_jk_navigation.md (bead sase-u.1). Captures
three timestamps for every j/k navigation:

- ``t_keypress``     -- action handler entry
- ``t_model_updated`` -- after ``current_idx`` mutation
- ``t_painted``      -- after the next Textual refresh cycle

Each sample is appended as JSON to ``~/.sase/perf/tui_jk.jsonl`` (override
with ``SASE_TUI_PERF_PATH``) and retained in a rolling in-memory window so
``JKPerfTimer.summary()`` can report p50/p95/max for each scenario.

The instrumentation is a no-op unless ``SASE_TUI_PERF=1`` is set in the
environment when ``AceApp`` initializes.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import deque
from pathlib import Path
from statistics import median
from typing import Any

log = logging.getLogger(__name__)

ENV_FLAG = "SASE_TUI_PERF"
ENV_PATH = "SASE_TUI_PERF_PATH"
DEFAULT_WINDOW = 200


def is_enabled() -> bool:
    """Return True when ``SASE_TUI_PERF=1`` is set in the environment."""
    return os.environ.get(ENV_FLAG) == "1"


def _perf_log_path() -> Path:
    """Return the JSONL path for perf samples (env-overridable)."""
    override = os.environ.get(ENV_PATH)
    if override:
        return Path(override)
    return Path.home() / ".sase" / "perf" / "tui_jk.jsonl"


class JKPerfTimer:
    """Per-app perf state. Records key-to-paint latencies for j/k actions.

    All times are captured with ``time.perf_counter()``. The timer holds a
    single in-flight sample at a time -- if a new ``begin()`` arrives before
    ``mark_painted()`` finishes the previous sample, the previous one is
    discarded. This is the right behavior for j/k navigation, where the user
    cares about the latency of the *most recent* keystroke, not stacked work.
    """

    def __init__(
        self,
        *,
        window: int = DEFAULT_WINDOW,
        log_path: Path | None = None,
    ) -> None:
        self.window = window
        self.log_path = log_path if log_path is not None else _perf_log_path()
        self._samples: deque[dict[str, Any]] = deque(maxlen=window)
        self._inflight: dict[str, Any] | None = None

    def begin(self, action: str, tab: str) -> None:
        """Record the start of a navigation action (``t_keypress``)."""
        self._inflight = {
            "action": action,
            "tab": tab,
            "t_keypress": time.perf_counter(),
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

    def _write(self, sample: dict[str, Any]) -> None:
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {
                            "action": sample["action"],
                            "tab": sample["tab"],
                            "t_keypress": sample["t_keypress"],
                            "model_ms": sample["model_ms"],
                            "paint_ms": sample["paint_ms"],
                        }
                    )
                    + "\n"
                )
        except OSError as e:
            log.debug("perf log write failed: %s", e)
