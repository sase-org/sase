"""Deterministic idle-CPU-diet budgets: zero-spawn ticks, skip counters, status overlay.

Wall-clock idle-host numbers live in ``docs/perf_runbook.md``. The chop-SDK
import-graph floor is ``tests/test_chop_import_budget.py``; the shipped
fs-trigger fire/skip contract is ``tests/test_axe_default_chop_triggers.py``.
This module locks those wins into lumberjack metrics and ``sase axe status``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.chop_runner_types import ChopRunOutcome
from sase.axe.config import AxeConfig, ChopConfig, LumberjackConfig, load_axe_config
from sase.axe.lumberjack import Lumberjack
from sase.axe.state import (
    LumberjackMetrics,
    format_lumberjack_chop_load,
    read_lumberjack_metrics,
    write_lumberjack_metrics,
)
from sase.core.time import get_timezone
from tests.test_axe_status_cli import _plain_render, _snapshot

pytest_plugins = ("tests._axe_lumberjack_fixtures",)


@patch("sase.axe.chop_runner.stream_chop_script")
@patch("sase.axe.chop_runner.discover_chop_script")
@patch("sase.axe.check_cycles.find_all_patches", return_value=[])
def test_idle_fs_guarded_tick_records_zero_spawns_and_trigger_skips(
    mock_find: MagicMock,
    mock_discover: MagicMock,
    mock_run: MagicMock,
) -> None:
    """Warmed-up hooks-lane ticks spawn nothing and count trigger skips."""
    axe_cfg = load_axe_config()
    guarded_chops = [
        chop
        for chop in axe_cfg.lumberjacks["hooks"].chops
        if chop.trigger.get("provider") == "fs"
    ]
    assert len(guarded_chops) == 7
    config = LumberjackConfig(
        name="hooks",
        description="Fast lane fixture",
        interval=5,
        chops=guarded_chops,
    )
    axe_config = AxeConfig(
        max_hook_runners=3, max_agent_runners=3, zombie_timeout_seconds=3600, query=""
    )
    from tests._axe_lumberjack_fixtures import streamed_ok

    mock_discover.return_value = Path("/fake/script")
    mock_run.side_effect = streamed_ok()

    lumberjack = Lumberjack("hooks", config, axe_config)
    lumberjack._run_tick()
    assert mock_run.call_count == len(guarded_chops)
    assert lumberjack._metrics.last_tick_spawns == len(guarded_chops)
    assert lumberjack._metrics.chops_spawned == len(guarded_chops)

    mock_run.reset_mock()
    lumberjack._run_tick()
    assert mock_run.call_count == 0
    assert lumberjack._metrics.last_tick_spawns == 0
    assert lumberjack._metrics.last_tick_skipped == len(guarded_chops)
    assert lumberjack._metrics.chops_skipped.get("trigger") == len(guarded_chops)
    persisted = read_lumberjack_metrics("hooks")
    assert persisted is not None
    assert persisted.last_tick_spawns == 0
    assert persisted.chops_skipped.get("trigger") == len(guarded_chops)


@patch("sase.axe.check_cycles.find_all_patches", return_value=[])
def test_run_every_and_no_op_feed_skip_and_ratio_counters(
    mock_find: MagicMock,
) -> None:
    tz = get_timezone()
    config = LumberjackConfig(
        name="throttled",
        description="Cadence fixture",
        interval=10,
        chops=[ChopConfig(name="slow_chop", description="", run_every=3600)],
    )
    axe_config = AxeConfig(
        max_hook_runners=3, max_agent_runners=3, zombie_timeout_seconds=3600, query=""
    )
    no_op = ChopRunOutcome(
        lumberjack_name="throttled",
        chop_name="slow_chop",
        status="no_op",
        run_id="run-noop",
        reason="waiting_markers_already_ready",
    )
    with patch(
        "sase.axe.lumberjack.run_configured_chop_once", return_value=no_op
    ) as run_chop:
        lumberjack = Lumberjack("throttled", config, axe_config)
        lumberjack._chop_timestamps["slow_chop"] = datetime.now(tz) - timedelta(
            seconds=10
        )
        lumberjack._run_tick()
        assert run_chop.call_count == 0
        assert lumberjack._metrics.chops_skipped.get("run_every") == 1
        assert lumberjack._metrics.last_tick_spawns == 0

        lumberjack._chop_timestamps["slow_chop"] = datetime.now(tz) - timedelta(
            seconds=3601
        )
        lumberjack._run_tick()
        assert run_chop.call_count == 1
        assert lumberjack._metrics.chops_spawned == 1
        assert lumberjack._metrics.chops_no_op == 1
        assert lumberjack._metrics.chops_executed == 1
        assert lumberjack._metrics.no_op_ratio == 1.0
        assert lumberjack._metrics.last_tick_no_ops == 1


@patch("sase.axe.check_cycles.find_all_patches", return_value=[])
def test_inhibited_preflight_skip_is_counted(
    mock_find: MagicMock,
) -> None:
    config = LumberjackConfig(
        name="guarded",
        description="Guard fixture",
        interval=10,
        chops=[ChopConfig(name="idle_only", description="")],
    )
    axe_config = AxeConfig(
        max_hook_runners=3, max_agent_runners=3, zombie_timeout_seconds=3600, query=""
    )
    skipped = ChopRunOutcome(
        lumberjack_name="guarded",
        chop_name="idle_only",
        status="skipped",
        run_id="run-skip",
        reason="agent_runners at max",
        skip_reason="inhibited",
    )
    with patch("sase.axe.lumberjack.run_configured_chop_once", return_value=skipped):
        lumberjack = Lumberjack("guarded", config, axe_config)
        lumberjack._run_tick()
    assert lumberjack._metrics.chops_spawned == 0
    assert lumberjack._metrics.chops_skipped.get("inhibited") == 1
    assert lumberjack._metrics.last_tick_skipped == 1


def test_metrics_json_round_trips_skip_buckets_and_ignores_unknown_keys(
    temp_state_dir: Path,
) -> None:
    metrics = LumberjackMetrics(
        cycles_run=3,
        chops_executed=2,
        chops_spawned=4,
        chops_no_op=3,
        chops_skipped={"trigger": 7, "run_every": 1, "inhibited": 2},
        last_tick_spawns=0,
        last_tick_skipped=7,
        spawn_rate_per_minute=0.4,
        no_op_ratio=0.75,
    )
    write_lumberjack_metrics("hooks", metrics)
    loaded = read_lumberjack_metrics("hooks")
    assert loaded is not None
    assert loaded.chops_skipped == {"trigger": 7, "run_every": 1, "inhibited": 2}
    assert loaded.spawn_rate_per_minute == 0.4
    assert loaded.no_op_ratio == 0.75

    metrics_path = temp_state_dir / "lumberjacks" / "hooks" / "metrics.json"
    payload = metrics_path.read_text(encoding="utf-8")
    metrics_path.write_text(
        payload.replace("{", '{"future_field": true, ', 1),
        encoding="utf-8",
    )
    reloaded = read_lumberjack_metrics("hooks")
    assert reloaded is not None
    assert reloaded.chops_spawned == 4


def test_axe_status_human_render_surfaces_spawn_rate_and_noop_ratio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metrics = LumberjackMetrics(
        chops_executed=10,
        chops_spawned=10,
        chops_no_op=8,
        chops_skipped={"trigger": 40, "run_every": 2, "inhibited": 0},
        last_tick_spawns=0,
        last_tick_skipped=7,
        spawn_rate_per_minute=0.4,
        no_op_ratio=0.8,
    )
    import sase.axe.status_render as status_render

    monkeypatch.setattr(status_render, "read_lumberjack_metrics", lambda name: metrics)
    output = _plain_render(_snapshot())
    folded = " ".join(output.split())
    assert "Chop load" in folded
    assert "0.4 spawns/min" in folded
    assert "no-op 80%" in folded
    assert "last tick 0 spawned / 7 skipped" in folded
    assert "0.4/min" in folded
    assert "no-op=80%" in folded
    assert "tick 0/7" in folded
    assert "t=40 re=2 inh=0" in folded


def test_format_lumberjack_chop_load_degrades_without_metrics() -> None:
    assert format_lumberjack_chop_load(None) == "-"
    empty = LumberjackMetrics()
    text = format_lumberjack_chop_load(empty)
    assert "0.0/min" in text
    assert "no-op=n/a" in text
    assert "t=0 re=0 inh=0" in text


def test_axe_status_json_wire_does_not_embed_chop_load() -> None:
    """The portable status snapshot stays schema-version-1; load lives in metrics.json."""
    import json

    import sase.axe.status_render as status_render

    stream = StringIO()
    status_render.render_axe_status_json(_snapshot(), stream=stream)
    payload = json.loads(stream.getvalue())
    assert "spawn_rate_per_minute" not in payload
    assert "chops_skipped" not in payload
    assert payload["schema_version"] == 1
