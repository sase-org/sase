"""Tests for agent-hold pending capture in agent_hold_facade."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.core.agent_hold_facade import (
    _capture_pending_targets,
    current_armer_wire,
    format_pending_capture,
    format_stored_capture,
    preview_pending_capture,
)


def test_capture_pending_targets_buckets_waiting_queued_and_running() -> None:
    entries = [
        SimpleNamespace(status="WAITING", artifacts_dir="/a/w1"),
        SimpleNamespace(status="WAITING", artifacts_dir="/a/w2"),
        SimpleNamespace(status="QUEUED", artifacts_dir="/a/q1"),
        SimpleNamespace(status="RUNNING", artifacts_dir="/a/r1"),
        SimpleNamespace(status="STARTING", artifacts_dir="/a/s1"),
    ]
    with patch(
        "sase.integrations.agent_list_entries.agent_list_entries",
        return_value=entries,
    ) as mock_entries:
        capture = _capture_pending_targets(project="proj")

    mock_entries.assert_called_once_with(project="proj")
    assert capture.waiting_count == 2
    assert capture.queued_count == 1
    assert capture.skipped_running_count == 2
    assert set(capture.artifact_dirs) == {"/a/w1", "/a/w2", "/a/q1"}


def test_preview_pending_capture_host_scope_ignores_project() -> None:
    entries = [
        SimpleNamespace(status="WAITING", artifacts_dir="/a/w1"),
        SimpleNamespace(status="QUEUED", artifacts_dir="/a/q1"),
        SimpleNamespace(status="RUNNING", artifacts_dir="/a/r1"),
    ]
    with patch(
        "sase.integrations.agent_list_entries.agent_list_entries",
        return_value=entries,
    ) as mock_entries:
        capture = preview_pending_capture("host", project="proj")

    mock_entries.assert_called_once_with(project=None)
    assert capture is not None
    assert capture.waiting_count == 1
    assert capture.queued_count == 1
    assert capture.skipped_running_count == 1


def test_preview_pending_capture_project_scope_passes_project() -> None:
    with patch(
        "sase.integrations.agent_list_entries.agent_list_entries",
        return_value=[],
    ) as mock_entries:
        preview_pending_capture("project", project="proj")

    mock_entries.assert_called_once_with(project="proj")


def test_preview_pending_capture_is_fail_soft() -> None:
    with patch(
        "sase.integrations.agent_list_entries.agent_list_entries",
        side_effect=RuntimeError("boom"),
    ):
        assert preview_pending_capture("project", project="proj") is None


def test_format_pending_capture_renders_counts() -> None:
    with patch(
        "sase.integrations.agent_list_entries.agent_list_entries",
        return_value=[
            SimpleNamespace(status="WAITING", artifacts_dir="/a/w1"),
            SimpleNamespace(status="WAITING", artifacts_dir="/a/w2"),
            SimpleNamespace(status="WAITING", artifacts_dir="/a/w3"),
            SimpleNamespace(status="WAITING", artifacts_dir="/a/w4"),
            SimpleNamespace(status="QUEUED", artifacts_dir="/a/q1"),
            SimpleNamespace(status="QUEUED", artifacts_dir="/a/q2"),
            SimpleNamespace(status="RUNNING", artifacts_dir="/a/r1"),
            SimpleNamespace(status="RUNNING", artifacts_dir="/a/r2"),
            SimpleNamespace(status="RUNNING", artifacts_dir="/a/r3"),
        ],
    ):
        capture = preview_pending_capture("project", project="proj")

    assert format_pending_capture(capture) == (
        "captures 4 waiting + 2 queued; skips 3 running"
    )


def test_format_pending_capture_none_returns_none() -> None:
    assert format_pending_capture(None) is None


def test_capture_pending_targets_excludes_armer_kin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.core.agent_hold_facade._project_for_cwd", lambda: "scratch"
    )
    armer = current_armer_wire(env={}, pid_override=4321)
    armer["kind"] = "agent"
    armer["agent_name"] = "holder.worker"
    armer["family"] = "holder.worker"
    armer["clan"] = "builders"
    armer["key"] = "agent:holder.worker"
    entries = [
        SimpleNamespace(
            status="WAITING",
            artifacts_dir="/a/kin",
            name="holder.worker",
            agent_family="holder.worker",
            agent_clan="builders",
            project="scratch",
            timestamp="20260910120000",
        ),
        SimpleNamespace(
            status="WAITING",
            artifacts_dir="/a/w1",
            name="target.agent--code",
            agent_family="target.agent",
            agent_clan="ops",
            project="scratch",
            timestamp="20260910120001",
        ),
        SimpleNamespace(
            status="QUEUED",
            artifacts_dir="/a/q1",
            name="other.agent--code",
            agent_family="other.agent",
            agent_clan="ops",
            project="scratch",
            timestamp="20260910120002",
        ),
        SimpleNamespace(
            status="RUNNING",
            artifacts_dir="/a/r1",
            name="running.agent--code",
            agent_family="running.agent",
            agent_clan="ops",
            project="scratch",
            timestamp="20260910120003",
        ),
    ]
    with patch(
        "sase.integrations.agent_list_entries.agent_list_entries",
        return_value=entries,
    ):
        capture = _capture_pending_targets(
            project="scratch", armer=armer, scope="project"
        )

    assert capture.waiting_count == 1
    assert capture.queued_count == 1
    assert capture.skipped_running_count == 1
    assert set(capture.artifact_dirs) == {"/a/w1", "/a/q1"}


def test_legacy_hold_renders_capture_as_not_recorded() -> None:
    assert format_stored_capture({"armer": {"key": "legacy"}}) == "capture not recorded"
    assert (
        format_stored_capture(
            {
                "capture": {
                    "waiting_count": 2,
                    "queued_count": 1,
                    "skipped_running_count": 4,
                }
            }
        )
        == "2 waiting + 1 queued; skipped 4 running"
    )
