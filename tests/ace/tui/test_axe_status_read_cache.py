"""Filesystem tests for mtime/size keyed axe status reads."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.axe_display import (
    AxeCollectedData,
    AxeStatusReadCache,
    collect_axe_status_data,
)
from sase.axe.state import (
    ChopRunEntry,
    append_chop_run_output,
    chop_run_meta_path,
    write_chop_run,
)
from tests.ace.tui._axe_collector_helpers import (
    FakeAxeConfig as _FakeAxeConfig,
    lumberjack_config as _lj_cfg,
    make_metrics as _make_metrics,
    make_status as _make_status,
)
from tests.conftest import redirect_sase_home


def _entry(chop: str, run_id: str) -> ChopRunEntry:
    return ChopRunEntry(
        run_id=run_id,
        lumberjack_name="hooks",
        chop_name=chop,
        started_at="2026-05-11T10:00:00",
        finished_at="2026-05-11T10:00:01",
        duration_ms=1000,
        status="success",
        exit_code=0,
        output_bytes=6,
        output_log=f"{run_id}.log",
    )


def _collect(
    cache: AxeStatusReadCache,
    *,
    tail_chop_keys: frozenset[tuple[str, str]] | None = None,
) -> AxeCollectedData:
    config = _FakeAxeConfig({"hooks": _lj_cfg("hooks", ["fast", "slow"])})
    with (
        patch(
            "sase.ace.tui.actions.axe_display._data.get_axe_process_module"
        ) as get_proc,
        patch("sase.ace.tui.actions.axe_display._data.read_metrics", return_value=None),
        patch("sase.axe.config.load_axe_config", return_value=config),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_lumberjack_status",
            return_value=_make_status("hooks"),
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_lumberjack_metrics",
            return_value=_make_metrics(),
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.get_active_slots", return_value=[]
        ),
    ):
        proc = get_proc.return_value
        proc.is_axe_running.return_value = False
        proc.get_axe_status.return_value = None
        return collect_axe_status_data(
            cache=cache,
            tail_chop_keys=(
                frozenset({("hooks", "fast")})
                if tail_chop_keys is None
                else tail_chop_keys
            ),
        )


def test_unchanged_run_records_are_not_reparsed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A quiet tick reuses parsed run JSON keyed by path/mtime/size."""
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    write_chop_run(_entry("fast", "20260511T100100_000000"), output="fast\n")
    write_chop_run(_entry("slow", "20260511T100200_000000"), output="slow\n")
    cache = AxeStatusReadCache()

    first = _collect(cache)
    assert first.stats.run_json_parses == 2
    assert first.chop_snapshots[("hooks", "fast")].runs[0].output_tail == "fast\n"

    second = _collect(cache)
    assert second.stats.run_json_parses == 0
    assert second.stats.run_index_reads == 0
    assert second.stats.log_tail_reads == 0
    assert second.stats.file_opens == 0
    assert second.chop_snapshots[("hooks", "fast")].runs[0].entry.run_id == (
        "20260511T100100_000000"
    )


def test_run_json_mtime_change_invalidates_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    run_id = "20260511T100100_000000"
    write_chop_run(_entry("fast", run_id), output="fast\n")
    cache = AxeStatusReadCache()
    _collect(cache, tail_chop_keys=frozenset({("hooks", "fast")}))

    meta = chop_run_meta_path("hooks", "fast", run_id)
    payload = meta.read_text(encoding="utf-8").replace("success", "failure")
    meta.write_text(payload, encoding="utf-8")

    refreshed = _collect(cache, tail_chop_keys=frozenset({("hooks", "fast")}))
    assert refreshed.stats.run_json_parses == 1
    assert refreshed.chop_snapshots[("hooks", "fast")].runs[0].entry.status == (
        "failure"
    )


def test_log_tail_rereads_only_when_size_grows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    run_id = "20260511T100100_000000"
    write_chop_run(_entry("fast", run_id), output="line1\n")
    cache = AxeStatusReadCache()
    first = _collect(cache, tail_chop_keys=frozenset({("hooks", "fast")}))
    assert first.stats.log_tail_reads >= 1

    quiet = _collect(cache, tail_chop_keys=frozenset({("hooks", "fast")}))
    assert quiet.stats.log_tail_reads == 0
    assert quiet.chop_snapshots[("hooks", "fast")].runs[0].output_tail == "line1\n"

    append_chop_run_output("hooks", "fast", run_id, "line2\n")
    grown = _collect(cache, tail_chop_keys=frozenset({("hooks", "fast")}))
    assert grown.stats.log_tail_reads == 1
    assert "line2" in grown.chop_snapshots[("hooks", "fast")].runs[0].output_tail
