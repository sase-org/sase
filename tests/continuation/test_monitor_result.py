"""Continuation monitor-result capture tests."""

from __future__ import annotations

import json
from pathlib import Path
import threading
import time
from unittest.mock import patch

import pytest

from tests._continuation_capture_helpers import json_record


def _base_monitor_meta(tmp_path: Path, starter: Path) -> dict[str, object]:
    return {
        "monitor_id": "m1",
        "name": "acme--mon",
        "monitor_command": "true",
        "monitor_cwd": str(tmp_path),
        "run_started_at": "2026-09-16T00:00:00Z",
        "monitor_next_action": "finish it",
        "monitor_state": "completed",
        "monitor_starter_agent": "acme",
        "monitor_starter_artifacts_dir": str(starter),
        "workspace_dir": str(tmp_path),
        "workspace_num": 1,
    }


def test_monitor_result_hydrates_starter_parent_and_blocks_when_missing(
    tmp_path: Path,
) -> None:
    from sase.continuation_capture import (
        continuation_dispatch_blocked_reason,
        persist_monitor_result,
    )

    starter = tmp_path / "starter"
    starter.mkdir()
    (starter / "agent_meta.json").write_text(
        json.dumps({"continuation_node_id": "agent-delta:starter:1"}),
        encoding="utf-8",
    )
    monitor = tmp_path / "monitor"
    monitor.mkdir()
    meta = {
        "monitor_id": "m1",
        "name": "acme--mon",
        "monitor_command": "true",
        "monitor_cwd": str(tmp_path),
        "run_started_at": "2026-09-12T00:00:00Z",
        "monitor_next_action": "finish it",
        "monitor_starter_agent": "acme",
        "monitor_starter_artifacts_dir": str(starter),
        "workspace_dir": str(tmp_path),
        "workspace_num": 1,
    }
    with (
        patch("sase.core.continuation_facade.validate_monitor_result"),
        patch("sase.core.continuation_facade.validate_continuation_node"),
    ):
        published = persist_monitor_result(
            artifacts_dir=monitor,
            meta=meta,
            monitor_state="completed",
            exit_code=0,
            elapsed_seconds=1.0,
            stopped_at="2026-09-12T00:00:01Z",
            diagnostic_manifest=None,
            retained_log={"log_ref": "local:log", "complete": True},
            project_name="proj",
            update_meta=False,
        )
    node = json_record(
        monitor
        / "continuation"
        / published.node_ref.removeprefix("local:continuation/")
    )
    assert node["parent_ids"] == ["agent-delta:starter:1"]
    assert continuation_dispatch_blocked_reason(meta) is None

    blocked_meta = {
        "monitor_next_action": "finish it",
        "continuation_capture_disposition": "needs_recovery",
        "continuation_capture_error": "starter missing",
    }
    assert continuation_dispatch_blocked_reason(blocked_meta) == "starter missing"


def test_persist_monitor_result_waits_for_a_starter_still_finalizing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A starter that settles mid-wait still yields a hydrated parent id.

    Reproduces the sase-11o.1 race: the monitor's result-capture publish
    happens while the starter is still finalizing (no ``continuation_node_id``
    or ``done.json`` yet). The publish path must wait, bounded, instead of
    stamping ``needs_recovery`` immediately.
    """
    from sase.continuation_capture import persist_monitor_result

    monkeypatch.setattr(
        "sase.shells.followup.DEFAULT_STARTER_SETTLE_TIMEOUT_SECONDS", 2.0
    )
    monkeypatch.setattr("sase.shells.followup.STARTER_SETTLE_POLL_SECONDS", 0.02)

    starter = tmp_path / "starter"
    starter.mkdir()
    (starter / "agent_meta.json").write_text(
        json.dumps({"name": "acme"}), encoding="utf-8"
    )
    monitor = tmp_path / "monitor"
    monitor.mkdir()
    meta = _base_monitor_meta(tmp_path, starter)

    def _settle_starter() -> None:
        time.sleep(0.15)  # sase-test-wait: create a deterministic starter-settle race
        (starter / "agent_meta.json").write_text(
            json.dumps(
                {"name": "acme", "continuation_node_id": "agent-delta:starter:1"}
            ),
            encoding="utf-8",
        )
        (starter / "done.json").write_text("{}", encoding="utf-8")

    thread = threading.Thread(target=_settle_starter)
    thread.start()
    try:
        with (
            patch("sase.core.continuation_facade.validate_monitor_result"),
            patch("sase.core.continuation_facade.validate_continuation_node"),
        ):
            started = time.monotonic()
            published = persist_monitor_result(
                artifacts_dir=monitor,
                meta=meta,
                monitor_state="completed",
                exit_code=0,
                elapsed_seconds=1.0,
                stopped_at="2026-09-16T00:00:01Z",
                diagnostic_manifest=None,
                retained_log={"log_ref": "local:log", "complete": True},
                project_name="proj",
                update_meta=False,
            )
            elapsed = time.monotonic() - started
    finally:
        thread.join(timeout=5.0)
    assert not thread.is_alive()
    assert elapsed < 2.0

    node = json_record(
        monitor
        / "continuation"
        / published.node_ref.removeprefix("local:continuation/")
    )
    assert node["parent_ids"] == ["agent-delta:starter:1"]
    assert meta["continuation_capture_disposition"] == "ok"


def test_persist_monitor_result_stamps_needs_recovery_after_bounded_wait(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A starter that never settles still bounds the wait -- no hang."""
    from sase.continuation_capture import persist_monitor_result

    monkeypatch.setattr(
        "sase.shells.followup.DEFAULT_STARTER_SETTLE_TIMEOUT_SECONDS", 0.05
    )
    monkeypatch.setattr("sase.shells.followup.STARTER_SETTLE_POLL_SECONDS", 0.01)

    starter = tmp_path / "starter"
    starter.mkdir()
    (starter / "agent_meta.json").write_text(
        json.dumps({"name": "acme"}), encoding="utf-8"
    )
    monitor = tmp_path / "monitor"
    monitor.mkdir()
    meta = _base_monitor_meta(tmp_path, starter)

    with (
        patch("sase.core.continuation_facade.validate_monitor_result"),
        patch("sase.core.continuation_facade.validate_continuation_node"),
    ):
        started = time.monotonic()
        persist_monitor_result(
            artifacts_dir=monitor,
            meta=meta,
            monitor_state="completed",
            exit_code=0,
            elapsed_seconds=1.0,
            stopped_at="2026-09-16T00:00:01Z",
            diagnostic_manifest=None,
            retained_log={"log_ref": "local:log", "complete": True},
            project_name="proj",
            update_meta=False,
        )
        elapsed = time.monotonic() - started

    assert elapsed < 2.0
    assert meta["continuation_capture_disposition"] == "needs_recovery"
    from sase.continuation_capture.monitor import _MISSING_STARTER_PARENT_ERROR

    assert meta["continuation_capture_error"] == _MISSING_STARTER_PARENT_ERROR


def test_persist_monitor_result_skips_the_wait_for_stopped_monitors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stopped/lost monitors must keep bypassing the starter-parent check."""
    from sase.continuation_capture import persist_monitor_result

    def _fail(*_args: object, **_kwargs: object) -> bool:
        raise AssertionError("stopped monitors must not wait for the starter")

    monkeypatch.setattr("sase.shells.followup.wait_for_starter_artifacts_dir", _fail)

    starter = tmp_path / "starter"
    starter.mkdir()
    (starter / "agent_meta.json").write_text(
        json.dumps({"name": "acme"}), encoding="utf-8"
    )
    monitor = tmp_path / "monitor"
    monitor.mkdir()
    meta = _base_monitor_meta(tmp_path, starter)
    meta["monitor_state"] = "stopped"

    with (
        patch("sase.core.continuation_facade.validate_monitor_result"),
        patch("sase.core.continuation_facade.validate_continuation_node"),
    ):
        persist_monitor_result(
            artifacts_dir=monitor,
            meta=meta,
            monitor_state="stopped",
            exit_code=None,
            elapsed_seconds=1.0,
            stopped_at="2026-09-16T00:00:01Z",
            diagnostic_manifest=None,
            retained_log={"log_ref": "local:log", "complete": True},
            project_name="proj",
            update_meta=False,
        )

    assert meta["continuation_capture_disposition"] == "ok"


def test_repair_missing_starter_parent_disposition_recovers_after_starter_settles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Settlement's one-shot re-check backfills the node record and manifest."""
    from sase.continuation_capture import (
        persist_monitor_result,
        repair_missing_starter_parent_disposition,
    )

    monkeypatch.setattr(
        "sase.shells.followup.DEFAULT_STARTER_SETTLE_TIMEOUT_SECONDS", 0.05
    )
    monkeypatch.setattr("sase.shells.followup.STARTER_SETTLE_POLL_SECONDS", 0.01)

    starter = tmp_path / "starter"
    starter.mkdir()
    (starter / "agent_meta.json").write_text(
        json.dumps({"name": "acme"}), encoding="utf-8"
    )
    monitor = tmp_path / "monitor"
    monitor.mkdir()
    meta = _base_monitor_meta(tmp_path, starter)

    with (
        patch("sase.core.continuation_facade.validate_monitor_result"),
        patch("sase.core.continuation_facade.validate_continuation_node"),
    ):
        published = persist_monitor_result(
            artifacts_dir=monitor,
            meta=meta,
            monitor_state="completed",
            exit_code=0,
            elapsed_seconds=1.0,
            stopped_at="2026-09-16T00:00:01Z",
            diagnostic_manifest=None,
            retained_log={"log_ref": "local:log", "complete": True},
            project_name="proj",
            update_meta=False,
        )
    assert meta["continuation_capture_disposition"] == "needs_recovery"
    node_before = json_record(
        monitor
        / "continuation"
        / published.node_ref.removeprefix("local:continuation/")
    )
    assert node_before["parent_ids"] == []
    manifest_before = json_record(
        monitor / "continuation" / "monitor_result_manifest.json"
    )

    # The starter settles in the gap between capture and settlement.
    (starter / "agent_meta.json").write_text(
        json.dumps({"name": "acme", "continuation_node_id": "agent-delta:starter:1"}),
        encoding="utf-8",
    )
    (starter / "done.json").write_text("{}", encoding="utf-8")

    recovered = repair_missing_starter_parent_disposition(monitor, meta)

    assert recovered is True
    assert meta["continuation_capture_disposition"] == "ok"
    assert meta["continuation_parent_node_ids"] == ["agent-delta:starter:1"]
    assert "continuation_capture_error" not in meta
    node_after = json_record(
        monitor
        / "continuation"
        / published.node_ref.removeprefix("local:continuation/")
    )
    assert node_after["parent_ids"] == ["agent-delta:starter:1"]
    manifest_after = json_record(
        monitor / "continuation" / "monitor_result_manifest.json"
    )
    assert manifest_after["parent_node_ids"] == ["agent-delta:starter:1"]
    assert manifest_after["node_sha256"] != manifest_before["node_sha256"]


def test_repair_missing_starter_parent_disposition_ignores_unrelated_causes(
    tmp_path: Path,
) -> None:
    """A ``needs_recovery`` disposition from an unrelated cause is left alone."""
    from sase.continuation_capture import repair_missing_starter_parent_disposition

    monitor = tmp_path / "monitor"
    monitor.mkdir()
    meta = {
        "continuation_capture_disposition": "needs_recovery",
        "continuation_capture_error": "portable capture failed for some other reason",
        "continuation_monitor_result_node_id": "monitor-result:whatever",
    }

    assert repair_missing_starter_parent_disposition(monitor, dict(meta)) is False
