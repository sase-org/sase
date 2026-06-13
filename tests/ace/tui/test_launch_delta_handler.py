"""Tests for launch-result delta refresh handling."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.ace.tui._launch_fan_out_helpers import _LaunchDeltaApp, _launch_result


def test_launch_delta_handler_schedules_exact_artifact_dirs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _LaunchDeltaApp()
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    app._handle_launch_results_delta(
        [
            _launch_result(
                0,
                project_name="proj",
                timestamp="260501_120000",
            )
        ]
    )

    assert app.broad_refreshes == []
    assert app.delta_refreshes == [
        (
            [
                str(
                    tmp_path
                    / ".sase"
                    / "projects"
                    / "proj"
                    / "artifacts"
                    / "ace-run"
                    / "20260501120000"
                )
            ],
            "launch",
        )
    ]


def test_launch_delta_handler_missing_result_falls_back_to_broad_refresh() -> None:
    app = _LaunchDeltaApp()

    app._handle_launch_results_delta([])

    assert app.delta_refreshes == []
    assert app.broad_refreshes == ["launch"]
    assert app._agents_refresh_trace_records[-1].fallback_reason == (
        "missing_launch_result"
    )
