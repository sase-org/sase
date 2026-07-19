"""Tests for forced-reuse agent-name wipe semantics."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.names import (
    _wipe,
    find_named_agent,
    get_reserved_agent_names,
    load_name_registry,
    lookup_registered_name,
    rebuild_name_registry,
    wipe_agent_name_for_reuse,
)
from sase.notifications.models import Notification
from sase.notifications.store import append_notification, load_notifications


def _artifact(
    home: Path,
    suffix: str,
    name: str,
    *,
    project: str = "proj",
    done: bool = False,
    meta: dict[str, object] | None = None,
) -> Path:
    path = home / ".sase" / "projects" / project / "artifacts" / "ace-run" / suffix
    path.mkdir(parents=True, exist_ok=True)
    payload = {"name": name, "workflow_name": name, **(meta or {})}
    (path / "agent_meta.json").write_text(json.dumps(payload), encoding="utf-8")
    if done:
        (path / "done.json").write_text(
            json.dumps({"name": name, "outcome": "completed"}),
            encoding="utf-8",
        )
    return path


def _bundle(home: Path, suffix: str, name: str, **extra: object) -> Path:
    path = home / ".sase" / "dismissed_bundles" / "202605" / f"{suffix}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"raw_suffix": suffix, "agent_name": name, "workflow_name": name, **extra}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


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
    artifacts_dir = _artifact(tmp_path, "20260508120000", "foo", done=True)
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
    artifacts_dir = _artifact(tmp_path, "20260508120000", "foo", done=True)

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        with patch(
            "sase.agent.names._wipe.delete_agent_artifact_index_artifacts"
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
        "sase.agent.names._wipe.update_agent_artifact_index_for_marker_mutation"
    ) as mock_update_index:
        _wipe._release_artifact_workspace(artifacts_dir)

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
        "sase.agent.names._wipe.update_agent_artifact_index_for_marker_mutation",
        side_effect=RuntimeError("index unavailable"),
    ):
        _wipe._release_artifact_workspace(artifacts_dir)

    assert not running_path.exists()


def test_wipe_live_agent_terminates_and_releases_workspace(
    tmp_path: Path,
) -> None:
    artifacts_dir = _artifact(tmp_path, "20260508120000", "foo", meta={"pid": 1234})

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        with (
            patch("sase.agent.names._wipe.is_process_alive", return_value=True),
            patch("sase.agent.names._wipe.os.killpg") as killpg,
            patch("sase.agent.names._wipe._release_artifact_workspace") as release,
        ):
            result = wipe_agent_name_for_reuse("foo")

    killpg.assert_called_once_with(1234, 15)
    release.assert_called_once_with(artifacts_dir)
    assert result.killed_processes == 1
    assert not artifacts_dir.exists()


def test_wipe_dismissed_bundle_only_agent_removes_bundle_and_index(
    tmp_path: Path,
) -> None:
    bundle_path = _bundle(tmp_path, "20260508120000", "foo")
    dismissed_index = tmp_path / ".sase" / "dismissed_agents.json"
    dismissed_index.write_text(
        json.dumps([["run", "foo", "20260508120000"], ["run", "bar", "bar-ts"]]),
        encoding="utf-8",
    )

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        with patch(
            "sase.agent.names._wipe.sync_dismissed_agent_artifact_index"
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
    parent = _artifact(tmp_path, "parent-ts", "foo")
    child = _artifact(
        tmp_path,
        "child-ts",
        "foo.child",
        meta={"parent_timestamp": "parent-ts"},
    )
    followup = _artifact(
        tmp_path,
        "followup-ts",
        "foo.code",
        meta={"parent_timestamp": "parent-ts", "role_suffix": ".code"},
    )
    unrelated = _artifact(tmp_path, "other-ts", "bar")

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        result = wipe_agent_name_for_reuse("foo")

        removed = set(result.artifact_dirs_removed)
        assert {str(parent), str(child), str(followup)} <= removed
        assert unrelated.exists()
        assert {"foo", "foo.child", "foo.code"}.isdisjoint(get_reserved_agent_names())
        assert "bar" in get_reserved_agent_names()


def test_wipe_retry_chain_and_bundle_descendants(tmp_path: Path) -> None:
    root = _artifact(
        tmp_path,
        "root-ts",
        "foo",
        done=True,
        meta={"retried_as_timestamp": "retry-ts"},
    )
    retry = _artifact(
        tmp_path,
        "retry-ts",
        "foo.retry",
        meta={"retry_of_timestamp": "root-ts", "retry_chain_root_timestamp": "root-ts"},
    )
    bundle_path = _bundle(
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


@pytest.mark.parametrize(
    ("container_kind", "container_name", "member_names", "container_meta"),
    [
        pytest.param(
            "clan",
            "research",
            ("research.worker", "research.finished"),
            {"agent_clan": "research", "agent_clan_generation": "clan-gen"},
            id="clan",
        ),
        pytest.param(
            "family",
            "review",
            ("review--0", "review--code"),
            {"agent_family": "review", "agent_family_parallel": False},
            id="family",
        ),
    ],
)
def test_wipe_container_name_preserves_member_artifacts_and_registry(
    tmp_path: Path,
    container_kind: str,
    container_name: str,
    member_names: tuple[str, str],
    container_meta: dict[str, object],
) -> None:
    artifacts_dir = _artifact(
        tmp_path,
        "member-ts",
        member_names[0],
        done=True,
        meta=container_meta,
    )
    bundle_path = _bundle(
        tmp_path,
        "bundle-ts",
        member_names[1],
        **container_meta,
    )

    with patch.object(Path, "home", return_value=tmp_path):
        before = rebuild_name_registry()
        owner = lookup_registered_name(container_name)
        assert owner is not None
        assert owner["container_kind"] == container_kind

        # Exercise both accepted owner forms across the two container kinds.
        wipe_target = container_name if container_kind == "clan" else owner
        result = wipe_agent_name_for_reuse(wipe_target)

        assert result.found is True
        assert result.skipped_container_kind == container_kind
        assert result.artifact_dirs_removed == ()
        assert result.bundle_paths_removed == ()
        assert artifacts_dir.exists()
        assert bundle_path.exists()
        assert load_name_registry() == before
        assert {container_name, *member_names} <= get_reserved_agent_names()
