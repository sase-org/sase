"""Tests for plan inventory artifact scanning and loader integration."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.console import Console

from sase.core.agent_artifact_paths import canonical_agent_artifact_path
from sase.core.paths import sase_projects_dir
from sase.main import plan_inventory as plan_inventory_module
from sase.main.plan_candidates import visible_pending_plan_notifications
from sase.main.plan_inventory import (
    build_plan_inventory,
    plan_inventory_to_json,
    render_plan_inventory,
)
from sase.notifications import pending_actions
from tests._plan_inventory_helpers import (
    LIVE_AGENT_TS as _LIVE_AGENT_TS,
    append_plan_notification as _append_plan_notification,
    archived_plan as _archived_plan,
    done_plan_snapshot as _done_plan_snapshot,
    live_agent as _live_agent,
    response_dir as _response_dir,
    write_agent_meta as _write_agent_meta,
)


def test_approved_plan_scan_stops_after_limit() -> None:
    for index in range(10):
        plan = _archived_plan(f"approved-fast-{index:02d}.md", minutes_ago=index + 1)
        _write_agent_meta(
            "demo",
            "workflow-plan",
            f"2026061313{index:02d}00",
            {
                "plan_approved": True,
                "plan_action": "approve",
                "plan_path": str(plan),
            },
            minutes_ago=index + 1,
        )
    for index in range(50):
        _write_agent_meta(
            "demo",
            "workflow-plan",
            f"2026061212{index:02d}00",
            {"plan_approved": False},
            minutes_ago=100 + index,
        )

    with (
        patch(
            "sase.main.plan_candidates._load_live_plan_agents_for_notifications",
            return_value=(),
        ),
        patch(
            "sase.main.plan_inventory.read_json_object",
            wraps=plan_inventory_module.read_json_object,
        ) as read_json,
    ):
        payload = plan_inventory_to_json(build_plan_inventory(limit=10))

    assert len(payload["approved"]) == 10
    assert read_json.call_count == 10


def test_approved_plan_metadata_read_only_for_selected_rows() -> None:
    """Plan-file metadata reads pay only for the rows returned, not every candidate.

    Requests only the ``approved`` status so the 15 candidates this scan's
    early break never inspects don't also get read as unrepresented
    (rejected) archived plans, which would confound the read count this test
    is isolating.
    """
    for index in range(20):
        plan = _archived_plan(f"approved-scan-{index:02d}.md", minutes_ago=index + 1)
        _write_agent_meta(
            "demo",
            "workflow-plan",
            f"2026061313{index:02d}00",
            {
                "plan_approved": True,
                "plan_action": "approve",
                "plan_path": str(plan),
            },
            minutes_ago=index + 1,
        )

    from sase.main import plan_inventory_paths as plan_inventory_paths_module

    with patch(
        "sase.main.plan_inventory_paths._read_plan_metadata",
        wraps=plan_inventory_paths_module._read_plan_metadata,
    ) as read_metadata:
        payload = plan_inventory_to_json(
            build_plan_inventory(limit=5, statuses=("approved",))
        )

    assert len(payload["approved"]) == 5
    assert read_metadata.call_count == 5


def test_rejected_plan_metadata_read_only_for_selected_rows() -> None:
    """Rejected inference sorts by mtime before reading any plan-file content."""
    for index in range(20):
        _archived_plan(f"rejected-scan-{index:02d}.md", minutes_ago=index + 1)

    from sase.main import plan_inventory_paths as plan_inventory_paths_module

    with patch(
        "sase.main.plan_inventory_paths._read_plan_metadata",
        wraps=plan_inventory_paths_module._read_plan_metadata,
    ) as read_metadata:
        payload = plan_inventory_to_json(build_plan_inventory(limit=5))

    assert len(payload["rejected"]) == 5
    read_names = {call.args[0].name for call in read_metadata.call_args_list}
    expected_names = {f"rejected-scan-{index:02d}.md" for index in range(5)}
    assert read_names == expected_names


def test_inventory_reads_each_status_plan_once_for_title_and_tier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proposed = _archived_plan("proposed-once.md", minutes_ago=3)
    approved = _archived_plan("approved-once.md", minutes_ago=2)
    rejected = _archived_plan("rejected-once.md", minutes_ago=1)
    _append_plan_notification(
        "abcdef12-plan-notification",
        proposed,
        _response_dir(tmp_path, "proposed-once"),
        minutes_ago=3,
    )
    _write_agent_meta(
        "demo",
        "workflow-plan",
        "20260613150000",
        {"plan_approved": True, "plan_path": str(approved)},
        minutes_ago=1,
    )
    expected = {proposed, approved, rejected}
    real_read_text = Path.read_text
    reads: list[Path] = []

    def read_text(
        path: Path,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> str:
        if path in expected:
            reads.append(path)
        return real_read_text(path, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", read_text)

    with patch(
        "sase.main.plan_candidates._load_live_plan_agents_for_notifications",
        return_value=(_live_agent(),),
    ):
        payload = plan_inventory_to_json(build_plan_inventory())

    assert payload["summary"]["proposed"] == 1
    assert payload["summary"]["approved_shown"] == 1
    assert payload["summary"]["rejected_shown"] == 1
    assert sorted(reads) == sorted(expected)


def test_approved_scan_cap_scales_with_limit() -> None:
    assert plan_inventory_module._approved_candidate_limit(10) == 2_000
    assert plan_inventory_module._approved_candidate_limit(50) == 5_000
    assert plan_inventory_module._approved_candidate_limit(200) == 20_000
    assert plan_inventory_module._approved_candidate_limit(0) is None


def test_finite_approved_scan_discloses_candidate_cap() -> None:
    meta_paths = tuple(
        Path(f"/artifacts/{index}/agent_meta.json") for index in range(3)
    )
    with (
        patch(
            "sase.main.plan_inventory._agent_meta_paths_newest_first",
            return_value=meta_paths,
        ),
        patch(
            "sase.main.plan_inventory._approved_candidate_limit",
            return_value=2,
        ),
        patch(
            "sase.main.plan_inventory.read_json_object",
            return_value={"plan_approved": False},
        ) as read_json,
    ):
        inventory = build_plan_inventory(limit=3)
        payload = plan_inventory_to_json(inventory)
        buffer = io.StringIO()
        render_plan_inventory(
            inventory,
            console=Console(
                file=buffer,
                force_terminal=False,
                color_system=None,
                width=100,
            ),
        )

    assert read_json.call_count == 2
    assert payload["summary"]["approved_scan_truncated"] is True
    assert "Scanned the newest 2 agent artifacts" in buffer.getvalue()
    assert "older approvals may exist" in buffer.getvalue()


def test_unlimited_approved_scan_reads_past_default_candidate_cap() -> None:
    meta_paths = tuple(
        Path(f"/artifacts/{index}/agent_meta.json") for index in range(2_001)
    )
    with (
        patch(
            "sase.main.plan_inventory._agent_meta_paths_newest_first",
            return_value=meta_paths,
        ),
        patch(
            "sase.main.plan_inventory.read_json_object",
            return_value={"plan_approved": False},
        ) as read_json,
    ):
        payload = plan_inventory_to_json(build_plan_inventory(limit=0))

    assert read_json.call_count == 2_001
    assert payload["summary"]["limit"] == 0
    assert "approved_scan_truncated" not in payload["summary"]


def test_visible_plan_notifications_loads_pending_store_once(
    tmp_path: Path,
) -> None:
    first_plan = _archived_plan("first.md", minutes_ago=5)
    second_plan = _archived_plan("second.md", minutes_ago=4)
    first_response = _response_dir(tmp_path, "first")
    second_response = _response_dir(tmp_path, "second")
    _append_plan_notification(
        "abcdef12-plan-notification",
        first_plan,
        first_response,
        minutes_ago=5,
        agent_timestamp="20260613120000",
    )
    _append_plan_notification(
        "12345678-plan-notification",
        second_plan,
        second_response,
        minutes_ago=4,
        agent_timestamp="20260613120100",
    )

    with patch.object(
        pending_actions,
        "_load_store",
        wraps=pending_actions._load_store,
    ) as load_store:
        visible = visible_pending_plan_notifications(
            agents=(
                _live_agent(raw_suffix="20260613120000"),
                _live_agent(raw_suffix="20260613120100"),
            )
        )

    assert [notification.id for notification in visible] == [
        "12345678-plan-notification",
        "abcdef12-plan-notification",
    ]
    load_store.assert_called_once_with(include_legacy=True)


def test_plan_inventory_exact_timestamp_fallback_ignores_recent_done_planner(
    tmp_path: Path,
) -> None:
    timestamp = "20260612120000"
    plan = _archived_plan("fallback.md", minutes_ago=5)
    response_dir = _response_dir(tmp_path, "fallback")
    _append_plan_notification(
        "abcdef12-plan-notification",
        plan,
        response_dir,
        minutes_ago=5,
        agent_timestamp=timestamp,
    )
    artifact_dir = sase_projects_dir() / "demo" / "artifacts" / "ace-run" / timestamp
    artifact_dir.mkdir(parents=True)

    with patch(
        "sase.ace.tui.models.agent_loader._scan_artifact_dirs_for_loader",
        return_value=_done_plan_snapshot(timestamp=timestamp),
    ) as scan_dirs:
        payload = plan_inventory_to_json(build_plan_inventory())

    assert payload["summary"]["proposed"] == 0
    assert payload["proposed"] == []
    scan_dirs.assert_called_once()


def test_plan_inventory_exact_timestamp_fallback_ignores_sharded_done_planner(
    tmp_path: Path,
) -> None:
    timestamp = "20260612120000"
    plan = _archived_plan("sharded-fallback.md", minutes_ago=5)
    response_dir = _response_dir(tmp_path, "sharded-fallback")
    _append_plan_notification(
        "abcdef12-plan-notification",
        plan,
        response_dir,
        minutes_ago=5,
        agent_timestamp=timestamp,
    )
    artifact_dir = canonical_agent_artifact_path(
        "demo",
        "ace-run",
        timestamp,
        projects_root=sase_projects_dir(),
    )
    artifact_dir.mkdir(parents=True)

    with patch(
        "sase.ace.tui.models.agent_loader._scan_artifact_dirs_for_loader",
        return_value=_done_plan_snapshot(timestamp=timestamp),
    ) as scan_dirs:
        payload = plan_inventory_to_json(build_plan_inventory())

    assert payload["summary"]["proposed"] == 0
    assert payload["proposed"] == []
    assert scan_dirs.call_args.args[0] == [artifact_dir]


def test_lightweight_live_plan_loader_ignores_unreviewed_done_plan(
    tmp_path: Path,
) -> None:
    from sase.ace.tui.models.agent_loader import load_live_plan_agents

    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    snapshot = _done_plan_snapshot()

    with (
        patch(
            "sase.ace.tui.models.agent_loader.default_agent_artifact_index_path",
            return_value=index_path,
        ),
        patch(
            "sase.ace.tui.models.agent_loader.query_agent_artifact_index",
            return_value=snapshot,
        ) as query_index,
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
        ) as source_scan,
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agent_steps_from_snapshot",
        ) as workflow_steps,
        patch(
            "sase.ace.tui.models._agent_status_apply.classify_persisted_diff_badges",
            side_effect=AssertionError("diff badges should be skipped"),
        ),
    ):
        agents = load_live_plan_agents()

    assert agents == []
    query_index.assert_called_once()
    assert query_index.call_args.kwargs["options"].include_prompt_step_markers is False
    source_scan.assert_not_called()
    workflow_steps.assert_not_called()
