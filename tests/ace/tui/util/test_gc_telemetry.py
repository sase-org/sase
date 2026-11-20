"""Public import facade for the split GC telemetry tests."""

from __future__ import annotations

import gc
import inspect
import os
import time
from asyncio import Task
from collections.abc import Iterator
from typing import Any
from pathlib import Path

import pytest

from sase.ace.tui.actions._startup_telemetry import StartupTelemetryMixin
from sase.ace.tui.util import _gc_telemetry_lifecycle as lifecycle_module
from sase.ace.tui.util import _gc_telemetry_recorder as recorder_module
from sase.ace.tui.util import gc_telemetry
from sase.ace.tui.util import startup_clock
from sase.ace.tui.util.gc_telemetry import (
    GCTelemetry,
    app_instance_id,
    default_executor_heartbeat_fields,
    gc_trigger,
    install_gc_telemetry,
    latest_rss_bytes,
    new_app_instance_id,
    note_last_input_mono,
    recent_collections,
    register_heartbeat_provider,
    uninstall_gc_telemetry,
    unregister_heartbeat_provider,
)
from ._gc_telemetry_test_support import (
    clock as clock,
    emitted as emitted,
    telemetry as telemetry,
)
from . import test_gc_telemetry_collection as collection_tests
from . import test_gc_telemetry_heartbeat as heartbeat_tests
from . import test_gc_telemetry_lifecycle as lifecycle_tests
from . import test_gc_telemetry_startup as startup_tests

_TEST_FUNCTIONS = {
    "test_queue_keeps_gen2_and_slow_collections_only": collection_tests,
    "test_callback_body_performs_no_io_or_locking": collection_tests,
    "test_rate_cap_reports_suppressed_count": collection_tests,
    "test_auxiliary_rows_are_flushed_off_the_calling_thread": collection_tests,
    "test_trigger_tag_lands_on_record": collection_tests,
    "test_trigger_nesting_restores_outer_tag": collection_tests,
    "test_recent_collections_filters_by_time": collection_tests,
    "test_full_collection_markers_for_idle_policy": collection_tests,
    "test_queue_bound_drops_oldest_without_growing": collection_tests,
    "test_pause_row_carries_start_ts_input_age_and_fault_delta": collection_tests,
    "test_callback_records_input_age_and_majflt": collection_tests,
    "test_heartbeat_reports_and_resets_young_notable_pauses": heartbeat_tests,
    "test_heartbeat_totals_stay_exact_despite_rate_cap": heartbeat_tests,
    "test_heartbeat_parses_proc_and_tracks_fault_delta": heartbeat_tests,
    "test_pressure_sampler_caches_swap_and_recent_major_fault_rate": heartbeat_tests,
    "test_heartbeat_window_spans_since_previous_heartbeat": heartbeat_tests,
    "test_heartbeat_degrades_cleanly_without_proc": heartbeat_tests,
    "test_default_executor_heartbeat_gauge_reports_backlog": heartbeat_tests,
    "test_default_executor_heartbeat_gauge_reports_no_executor": heartbeat_tests,
    "test_default_executor_heartbeat_gauge_reports_missing_loop": heartbeat_tests,
    "test_heartbeat_providers_contribute_without_clobbering_core": heartbeat_tests,
    "test_heartbeat_includes_stats_blocks_and_python_version": heartbeat_tests,
    "test_install_uninstall_restores_gc_callbacks": lifecycle_tests,
    "test_install_respects_kill_switch": lifecycle_tests,
    "test_latest_rss_bytes_without_active": lifecycle_tests,
    "test_testing_harness_does_not_auto_install": startup_tests,
    "test_exec_anchor_is_used_and_consumed": startup_tests,
    "test_exec_anchor_rejects_garbage_and_future": startup_tests,
    "test_app_instance_id_mint_and_accessor": startup_tests,
    "test_startup_record_carries_instance_and_version": startup_tests,
    "test_bind_perf_instance_registers_executor_without_running_loop": startup_tests,
}


def __getattr__(name: str) -> Any:
    try:
        module = _TEST_FUNCTIONS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    return getattr(module, name)


__all__ = (
    "gc",
    "inspect",
    "os",
    "time",
    "Task",
    "Iterator",
    "Path",
    "Any",
    "pytest",
    "StartupTelemetryMixin",
    "lifecycle_module",
    "recorder_module",
    "gc_telemetry",
    "startup_clock",
    "GCTelemetry",
    "app_instance_id",
    "default_executor_heartbeat_fields",
    "gc_trigger",
    "install_gc_telemetry",
    "latest_rss_bytes",
    "new_app_instance_id",
    "note_last_input_mono",
    "recent_collections",
    "register_heartbeat_provider",
    "uninstall_gc_telemetry",
    "unregister_heartbeat_provider",
    "clock",
    "emitted",
    "telemetry",
) + tuple(_TEST_FUNCTIONS)
