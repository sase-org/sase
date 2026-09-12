"""Unit coverage for ACE TUI heap sampling."""

from __future__ import annotations

import json
import tracemalloc
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.util import heap as heap_mod
from sase.ace.tui.util.heap import TUIHeapSampler, start_tui_heap_sampler


@pytest.fixture(autouse=True)
def _restore_tracemalloc() -> object:
    was_tracing = tracemalloc.is_tracing()
    yield
    if not was_tracing and tracemalloc.is_tracing():
        tracemalloc.stop()


def test_heap_sampler_is_inert_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_TUI_HEAP", raising=False)

    assert heap_mod.is_enabled() is False
    assert TUIHeapSampler.from_env() is None


def test_heap_sampler_writes_top_allocation_sites(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "tui_heap.jsonl"
    sampler = TUIHeapSampler(log_path=path, top_n=5, nframe=4)
    sampler.start_tracing()
    payload = [bytearray(1024) for _ in range(16)]

    sampler.write_sample(reason="unit")

    assert payload
    record = json.loads(path.read_text(encoding="utf-8").strip())
    assert record["reason"] == "unit"
    assert record["pid"] > 0
    assert record["current_bytes"] > 0
    assert record["peak_bytes"] >= record["current_bytes"]
    assert record["top_n"] == 5
    assert 0 < len(record["sites"]) <= 5
    first = record["sites"][0]
    assert first["filename"]
    assert first["lineno"] > 0
    assert first["size_bytes"] > 0
    assert first["count"] > 0
    assert first["traceback"]


def test_start_tui_heap_sampler_uses_pump_free_task(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    sampler = TUIHeapSampler(log_path=tmp_path / "heap.jsonl", interval_seconds=12.5)
    scheduled: list[tuple[str, str]] = []

    def fake_spawn(
        _owner: object,
        coro: Any,
        *,
        name: str,
        registry_attr: str,
    ) -> None:
        scheduled.append((name, registry_attr))
        coro.close()
        return None

    monkeypatch.setattr(heap_mod, "spawn_pump_free_task", fake_spawn)

    class DummyApp:
        _heap_sampler = sampler

        def __init__(self) -> None:
            self.intervals: list[tuple[float, object, str | None]] = []

        def set_interval(
            self,
            interval: float,
            callback: object,
            *,
            name: str | None = None,
        ) -> object:
            self.intervals.append((interval, callback, name))
            return SimpleNamespace(stop=lambda: None)

    app = DummyApp()
    timer = start_tui_heap_sampler(app)

    assert timer is not None
    assert scheduled == [("tui-heap-sample", "_heap_sampler_async_tasks")]
    assert app.intervals == [(12.5, app.intervals[0][1], "heap-sampler")]
