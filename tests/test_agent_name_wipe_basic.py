"""Basic wipe tests: done agents, artifact index, workspaces, bundles.

Split from ``tests.test_agent_name_wipe``; the original module re-exports
these tests so its import path keeps working.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.agent.names import (
    _wipe_execute,
    _wipe_scan,
    find_named_agent,
    get_reserved_agent_names,
    rebuild_name_registry,
    wipe_agent_name_for_reuse,
    wipe_agent_names_for_reuse,
)
from sase.notifications.models import Notification
from sase.notifications.store import append_notification, load_notifications

from tests._agent_name_wipe_helpers import make_wipe_artifact, make_wipe_bundle

__all__ = [
    "test_batch_wipe_shares_catalog_and_registry_rebuild",
    "test_release_artifact_workspace_ignores_index_refresh_failure",
    "test_release_artifact_workspace_updates_index_after_running_marker_delete",
    "test_wipe_deletes_artifact_index_rows_for_removed_dirs",
    "test_wipe_dismissed_bundle_only_agent_removes_bundle_and_index",
    "test_wipe_done_agent_clears_lookup_registry_and_notifications",
    "test_wipe_retry_chain_and_bundle_descendants",
    "test_wipe_workflow_parent_removes_children_and_followups",
]


def _notification(notification_id: str, **action_data: str) -> Notification:
    return Notification(
        id=notification_id,
        timestamp="2026-05-08T00:00:00-04:00",
        sender="test",
        action="JumpToAgent",
        action_data=action_data,
    )


def test_wipe_done_agent_clears_lookup_registry_and_notifications(
    tmp_path: Path,
) -> None:
    artifacts_dir = make_wipe_artifact(tmp_path, "20260508120000", "foo", done=True)
    history_path = tmp_path / ".sase" / "prompt_history.json"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text('{"prompts":[{"text":"%wait:foo"}]}', encoding="utf-8")
    notifications_file = tmp_path / ".sase" / "notifications" / "notifications.jsonl"

    with (
        patch.object(Path, "home", return_value=tmp_path),
        patch(
            "sase.notifications.store.NOTIFICATIONS_DIR", str(notifications_file.parent)
        ),
        patch("sase.notifications.store.NOTIFICATIONS_FILE", str(notifications_file)),
    ):
        append_notification(
            _notification("n1", raw_suffix="20260508120000", agent_name="foo")
        )
        rebuild_name_registry()

        result = wipe_agent_name_for_reuse("foo")

        assert result.found is True
        assert str(artifacts_dir) in result.artifact_dirs_removed
        assert "foo" not in get_reserved_agent_names()
        assert find_named_agent("foo") is None
        assert json.loads(history_path.read_text(encoding="utf-8"))["prompts"]
        assert load_notifications(include_dismissed=True)[0].dismissed is True


def test_wipe_deletes_artifact_index_rows_for_removed_dirs(tmp_path: Path) -> None:
    artifacts_dir = make_wipe_artifact(tmp_path, "20260508120000", "foo", done=True)

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        with patch(
            "sase.agent.names._wipe_execute.delete_agent_artifact_index_artifacts"
        ) as mock_delete_index:
            result = wipe_agent_name_for_reuse("foo")

    assert result.artifact_dirs_removed == (str(artifacts_dir.resolve()),)
    mock_delete_index.assert_called_once()
    assert set(mock_delete_index.call_args.args[0]) == {artifacts_dir.resolve()}


def test_release_artifact_workspace_updates_index_after_running_marker_delete(
    tmp_path: Path,
) -> None:
    artifacts_dir = (
        tmp_path
        / ".sase"
        / "projects"
        / "home"
        / "artifacts"
        / "ace-run"
        / "20260508120000"
    )
    artifacts_dir.mkdir(parents=True)
    running_path = artifacts_dir / "running.json"
    running_path.write_text(json.dumps({"pid": 1234}), encoding="utf-8")

    with patch(
        "sase.agent.names._wipe_execute.update_agent_artifact_index_for_marker_mutation"
    ) as mock_update_index:
        _wipe_execute._release_artifact_workspace(artifacts_dir)

    assert not running_path.exists()
    mock_update_index.assert_called_once_with(artifacts_dir)


def test_release_artifact_workspace_ignores_index_refresh_failure(
    tmp_path: Path,
) -> None:
    artifacts_dir = (
        tmp_path
        / ".sase"
        / "projects"
        / "home"
        / "artifacts"
        / "ace-run"
        / "20260508120000"
    )
    artifacts_dir.mkdir(parents=True)
    running_path = artifacts_dir / "running.json"
    running_path.write_text(json.dumps({"pid": 1234}), encoding="utf-8")

    with patch(
        "sase.agent.names._wipe_execute.update_agent_artifact_index_for_marker_mutation",
        side_effect=RuntimeError("index unavailable"),
    ):
        _wipe_execute._release_artifact_workspace(artifacts_dir)

    assert not running_path.exists()


def test_wipe_dismissed_bundle_only_agent_removes_bundle_and_index(
    tmp_path: Path,
) -> None:
    bundle_path = make_wipe_bundle(tmp_path, "20260508120000", "foo")
    dismissed_index = tmp_path / ".sase" / "dismissed_agents.json"
    dismissed_index.write_text(
        json.dumps([["run", "foo", "20260508120000"], ["run", "bar", "bar-ts"]]),
        encoding="utf-8",
    )

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        with patch(
            "sase.agent.names._wipe_execute.sync_dismissed_agent_artifact_index"
        ) as sync_index:
            result = wipe_agent_name_for_reuse("foo")

        assert str(bundle_path) in result.bundle_paths_removed
        assert result.dismissed_index_entries_removed == 1
        assert not bundle_path.exists()
        assert json.loads(dismissed_index.read_text(encoding="utf-8")) == [
            ["run", "bar", "bar-ts"]
        ]
        assert "foo" not in get_reserved_agent_names()
        sync_index.assert_called_once_with(force=True)


def test_wipe_workflow_parent_removes_children_and_followups(
    tmp_path: Path,
) -> None:
    parent = make_wipe_artifact(tmp_path, "parent-ts", "foo")
    child = make_wipe_artifact(
        tmp_path,
        "child-ts",
        "foo.child",
        meta={"parent_timestamp": "parent-ts"},
    )
    followup = make_wipe_artifact(
        tmp_path,
        "followup-ts",
        "foo.code",
        meta={"parent_timestamp": "parent-ts", "role_suffix": ".code"},
    )
    unrelated = make_wipe_artifact(tmp_path, "other-ts", "bar")

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        result = wipe_agent_name_for_reuse("foo")

        removed = set(result.artifact_dirs_removed)
        assert {str(parent), str(child), str(followup)} <= removed
        assert unrelated.exists()
        assert {"foo", "foo.child", "foo.code"}.isdisjoint(get_reserved_agent_names())
        assert "bar" in get_reserved_agent_names()


def test_wipe_retry_chain_and_bundle_descendants(tmp_path: Path) -> None:
    root = make_wipe_artifact(
        tmp_path,
        "root-ts",
        "foo",
        done=True,
        meta={"retried_as_timestamp": "retry-ts"},
    )
    retry = make_wipe_artifact(
        tmp_path,
        "retry-ts",
        "foo.retry",
        meta={"retry_of_timestamp": "root-ts", "retry_chain_root_timestamp": "root-ts"},
    )
    bundle_path = make_wipe_bundle(
        tmp_path,
        "bundle-child-ts",
        "foo.bundle",
        parent_timestamp="retry-ts",
    )

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        result = wipe_agent_name_for_reuse("foo")

        assert {str(root), str(retry)} <= set(result.artifact_dirs_removed)
        assert str(bundle_path) in result.bundle_paths_removed
        assert {"foo", "foo.retry", "foo.bundle"}.isdisjoint(get_reserved_agent_names())


def test_batch_wipe_shares_catalog_and_registry_rebuild(tmp_path: Path) -> None:
    foo = make_wipe_artifact(tmp_path, "20260724120000", "foo", done=True)
    bar = make_wipe_artifact(tmp_path, "20260724120100", "bar", done=True)
    bundle_path = make_wipe_bundle(
        tmp_path,
        "20260724120200",
        "foo.review",
        parent_timestamp=foo.name,
    )

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        with (
            patch(
                "sase.agent.names._wipe_scan._scan_artifacts",
                wraps=_wipe_scan._scan_artifacts,
            ) as scan_artifacts,
            patch(
                "sase.agent.names._wipe_scan._scan_bundles",
                wraps=_wipe_scan._scan_bundles,
            ) as scan_bundles,
            patch(
                "sase.agent.names._wipe_execute.rebuild_name_registry",
                wraps=_wipe_execute.rebuild_name_registry,
            ) as rebuild,
        ):
            results = wipe_agent_names_for_reuse(("foo", "bar"))

    assert scan_artifacts.call_count == 1
    assert scan_bundles.call_count == 1
    assert rebuild.call_count == 1
    assert {result.target_name for result in results} == {"foo", "bar"}
    assert {str(foo), str(bar)} <= {
        path for result in results for path in result.artifact_dirs_removed
    }
    assert str(bundle_path) in {
        path for result in results for path in result.bundle_paths_removed
    }
    assert not foo.exists()
    assert not bar.exists()
    assert not bundle_path.exists()
