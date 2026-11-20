"""Test gc telemetry startup tests."""

from __future__ import annotations

import gc
import os
import time
from asyncio import Task
from typing import Any

import pytest

from sase.ace.tui.actions._startup_telemetry import StartupTelemetryMixin
from sase.ace.tui.util import _gc_telemetry_lifecycle as lifecycle_module
from sase.ace.tui.util import gc_telemetry
from sase.ace.tui.util import startup_clock
from sase.ace.tui.util.gc_telemetry import app_instance_id, new_app_instance_id


class _StartupStub(StartupTelemetryMixin):
    def __init__(self) -> None:
        self.current_tab = "agents"
        self._startup_process_start_mono = 100.0
        self._startup_on_mount_mono: float | None = 101.0
        self._startup_first_paint_mono: float | None = 101.5
        self._startup_initial_tab = "agents"
        self._startup_agents_ready_mono: float | None = 102.0
        self._startup_axe_ready_mono: float | None = 103.0
        self._startup_visible_ready_mono: float | None = 102.0
        self._startup_telemetry_recorded = False
        self._startup_telemetry_async_tasks: set[Task[None]] = set()
        self._agents_first_load_done = True
        self._axe_first_load_done = True
        self._agents: list[Any] = []
        self._agents_refresh_active_source = "startup"
        self._agent_load_state = None
        self._app_instance_id = "stub-instance"


@pytest.mark.asyncio
async def test_testing_harness_does_not_auto_install() -> None:
    from contextlib import AsyncExitStack

    from sase.ace.testing import _startup as harness_startup

    assert (
        harness_startup._ORIGINAL_INSTALL_GC_TELEMETRY
        is gc_telemetry.install_gc_telemetry
    )
    before = list(gc.callbacks)
    async with AsyncExitStack() as stack:
        harness_startup._install_fast_startup_overrides(stack)
        assert harness_startup._gc_telemetry.install_gc_telemetry(object()) is None
        assert lifecycle_module._active is None
        assert list(gc.callbacks) == before


def test_exec_anchor_is_used_and_consumed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    anchor_ns = time.monotonic_ns() - 5_000_000_000
    monkeypatch.setenv(startup_clock.EXEC_MONO_NS_ENV, str(anchor_ns))
    startup_clock._process_start_mono = None
    try:
        assert startup_clock._ensure_process_start() == pytest.approx(
            anchor_ns / 1_000_000_000
        )
        assert startup_clock.EXEC_MONO_NS_ENV not in os.environ
    finally:
        startup_clock._process_start_mono = None
        startup_clock._cli_ready_mono = None
        startup_clock._app_imported_mono = None
        startup_clock._app_construct_start_mono = None
        startup_clock._app_construct_end_mono = None
        startup_clock._compose_start_mono = None
        startup_clock._compose_end_mono = None


def test_exec_anchor_rejects_garbage_and_future(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    startup_clock._process_start_mono = None
    try:
        monkeypatch.setenv(startup_clock.EXEC_MONO_NS_ENV, "not-a-number")
        fallback = startup_clock._ensure_process_start()
        assert isinstance(fallback, float)

        startup_clock._process_start_mono = None
        future_ns = time.monotonic_ns() + 60_000_000_000
        monkeypatch.setenv(startup_clock.EXEC_MONO_NS_ENV, str(future_ns))
        # /proc start time has 10ms resolution and the fallback spans I/O, so
        # compare with an absolute tolerance instead of the default relative one.
        assert startup_clock._ensure_process_start() == pytest.approx(
            fallback, abs=0.05
        )
    finally:
        startup_clock._process_start_mono = None


def test_app_instance_id_mint_and_accessor() -> None:
    first, second = new_app_instance_id(), new_app_instance_id()
    assert first and second and first != second
    assert app_instance_id(object()) is None
    assert app_instance_id(None) is None

    class _App:
        _app_instance_id = first

    assert app_instance_id(_App()) == first


def test_startup_record_carries_instance_and_version() -> None:
    record = _StartupStub()._build_startup_telemetry_record()
    assert record["event"] == "tui_startup"
    assert record["app_instance_id"] == "stub-instance"
    assert record["sase_version"] is None or isinstance(record["sase_version"], str)
    assert "source_revision" in record
    assert record["source_revision"] is None or isinstance(
        record["source_revision"], str
    )


def test_bind_perf_instance_registers_executor_without_running_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from sase.ace.tui.app import AceApp

    registered: dict[str, object] = {}

    def _register(name: str, fn: object) -> None:
        registered[name] = fn

    monkeypatch.setattr(gc_telemetry, "register_heartbeat_provider", _register)
    dummy = SimpleNamespace(
        _app_instance_id="abcd1234",
        _jk_perf=None,
        _prompt_activity=None,
        _default_executor_heartbeat=lambda: {},
    )
    AceApp._bind_perf_instance(dummy)
    assert "default_executor" in registered
    assert dummy._perf_event_loop is None
