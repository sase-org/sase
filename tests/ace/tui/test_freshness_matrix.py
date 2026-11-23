"""Publish the isolated-fixture freshness latency matrix.

Reproducible commands (from the opened sase checkout):

    pytest tests/ace/tui/test_freshness_watcher_path.py \\
           tests/ace/tui/test_freshness_surfaces.py \\
           tests/ace/tui/test_freshness_matrix.py -q
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from sase.ace.tui.util.fs_watcher import (
    DEFAULT_COALESCE_S,
    DEFAULT_DISPATCH_DEADLINE_S,
)
from tests.ace.tui._freshness_fixtures import (
    FreshnessApp,
    LatencySample,
    arm_live_agent_dir,
    format_latency_matrix,
    isolate_freshness_home,
    percentile,
    reset_freshness_observations,
    saw_callback_path,
    start_artifact_watcher,
    wait,
)
from tests.ace.tui._fs_watcher_helpers import LINUX_ONLY

_AGENT_SAMPLES = 5
_NOTIFY_SAMPLES = 3


def _stop(app: FreshnessApp) -> None:
    app._stop_artifact_watcher()
    app._stop_prompt_source_watcher()


def _record(
    case: str,
    mutation: float,
    app: FreshnessApp,
    *,
    cadence: float,
    gate: float = 0.0,
) -> LatencySample:
    return LatencySample(
        case=case,
        mutation_mono=mutation,
        callback_mono=app.last_callback_mono(),
        visible_mono=app.last_visible_mono(),
        cadence_s=cadence,
        activity_gate_s=gate,
        work=app.watcher_work(),
    )


@LINUX_ONLY
@pytest.mark.asyncio
async def test_freshness_latency_matrix_from_isolated_fixtures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = isolate_freshness_home(tmp_path, monkeypatch)
    app = FreshnessApp(sdd_beads_dir=home.beads_dir)
    app.current_tab = "agents"
    start_artifact_watcher(app, home)
    arm_live_agent_dir(app, home)
    samples: list[LatencySample] = []
    try:
        marker = home.agent_dir / "agent_meta.json"
        for index in range(_AGENT_SAMPLES):
            reset_freshness_observations(app)
            mutation = time.monotonic()
            marker.write_text(f'{{"n": {index}}}\n')
            assert wait(lambda: saw_callback_path(app, marker), timeout=3.0)
            await app._run_auto_refresh()
            samples.append(
                _record("agent_store", mutation, app, cadence=DEFAULT_COALESCE_S)
            )
            time.sleep(0.05)  # sase-test-wait: separate inotify samples

        for index in range(_NOTIFY_SAMPLES):
            app.callback_times.clear()
            app.visible_times.clear()
            app.notification_polls.clear()
            mutation = time.monotonic()
            (home.notifications_dir / f"note-{index}.json").write_text("{}")
            assert wait(lambda: bool(app.notification_polls), timeout=3.0)
            samples.append(
                _record("notification", mutation, app, cadence=DEFAULT_COALESCE_S)
            )

        app.callback_times.clear()
        mutation = time.monotonic()
        (home.beads_dir / "issues.jsonl").write_text("{}\n")
        assert wait(lambda: "schedule_patches" in app.refresh_calls, timeout=3.0)
        samples.append(_record("bead_store", mutation, app, cadence=DEFAULT_COALESCE_S))

        ignored_before = app.watcher_work().get("ui_dispatches", 0)
        for index in range(6):
            (home.agent_dir / f".burst{index}.swp").write_text("x")
        time.sleep(0.45)  # sase-test-wait: ignored-only coalesce window
        ignored_after = app.watcher_work()
        samples.append(
            LatencySample(
                case="ignored_only",
                mutation_mono=time.monotonic(),
                callback_mono=None,
                visible_mono=None,
                cadence_s=DEFAULT_COALESCE_S,
                work={
                    "ui_dispatches": ignored_after.get("ui_dispatches", 0)
                    - ignored_before,
                    "ignored_events": ignored_after.get("ignored_events", 0),
                },
            )
        )
    finally:
        stats = app.watcher_work()
        _stop(app)

    callbacks = [
        sample.event_to_callback_s
        for sample in samples
        if sample.case != "ignored_only" and sample.event_to_callback_s is not None
    ]
    visibles = [
        sample.event_to_visible_s
        for sample in samples
        if sample.case != "ignored_only" and sample.event_to_visible_s is not None
    ]
    assert callbacks
    assert visibles
    assert percentile(callbacks, 95) <= DEFAULT_DISPATCH_DEADLINE_S + 0.5
    assert max(callbacks) <= DEFAULT_DISPATCH_DEADLINE_S + 0.6
    assert percentile(visibles, 95) <= DEFAULT_DISPATCH_DEADLINE_S + 0.8
    ignored = next(sample for sample in samples if sample.case == "ignored_only")
    assert ignored.work.get("ui_dispatches", 0) == 0

    matrix = format_latency_matrix(samples)
    payload = {
        "cadence": {
            "coalesce_s": DEFAULT_COALESCE_S,
            "dispatch_deadline_s": DEFAULT_DISPATCH_DEADLINE_S,
        },
        "watcher_totals": stats,
        "samples": [
            {
                "case": sample.case,
                "event_to_callback_s": sample.event_to_callback_s,
                "event_to_visible_s": sample.event_to_visible_s,
                "cadence_s": sample.cadence_s,
                "activity_gate_s": sample.activity_gate_s,
                "work": sample.work,
            }
            for sample in samples
        ],
        "matrix_markdown": matrix,
        "fixture_commands": [
            "pytest tests/ace/tui/test_freshness_watcher_path.py tests/ace/tui/test_freshness_surfaces.py tests/ace/tui/test_freshness_matrix.py -q",
        ],
    }
    report = tmp_path / "freshness-latency-matrix.json"
    report.write_text(json.dumps(payload, indent=2) + "\n")
    print(matrix)
    assert "agent_store" in matrix
    assert report.is_file()
