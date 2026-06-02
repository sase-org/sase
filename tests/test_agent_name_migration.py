"""Tests for historical auto-name namespace migration."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.agent.names import get_next_auto_name, run_historical_auto_name_migration


def _artifact(home: Path, suffix: str, meta: dict[str, object]) -> Path:
    path = home / ".sase" / "projects" / "proj" / "artifacts" / "ace-run" / suffix
    path.mkdir(parents=True, exist_ok=True)
    (path / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return path


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_migrates_artifacts_refs_notifications_and_history(tmp_path: Path) -> None:
    old = _artifact(
        tmp_path,
        "20260508120000",
        {"name": "a", "workflow_name": "a", "wait_for": ["b", "sase-z"]},
    )
    (old / "done.json").write_text(
        json.dumps({"name": "a", "workflow_name": "a"}),
        encoding="utf-8",
    )
    dependent = _artifact(
        tmp_path,
        "20260508120500",
        {"name": "b.1", "workflow_name": "b", "wait_for": ["a"]},
    )
    (dependent / "waiting.json").write_text(
        json.dumps({"waiting_for": ["a"]}),
        encoding="utf-8",
    )
    (dependent / "raw_xprompt.md").write_text(
        "%w:a\n#fork:b.1 continue\n#resume:b.1 legacy continue\n", encoding="utf-8"
    )
    bundle = tmp_path / ".sase" / "dismissed_bundles" / "202605" / "20260508121000.json"
    bundle.parent.mkdir(parents=True)
    bundle.write_text(
        json.dumps({"agent_name": "c", "workflow_name": "c.plan"}),
        encoding="utf-8",
    )
    history = tmp_path / ".sase" / "prompt_history.json"
    history.write_text(
        json.dumps(
            {
                "prompts": [
                    {
                        "text": "%wait:a,c\n#fork(b.1) run",
                        "branch_or_workspace": "proj",
                        "timestamp": "260508_121500",
                        "last_used": "260508_121500",
                        "workspace": "proj",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    notifications = tmp_path / ".sase" / "notifications" / "notifications.jsonl"
    notifications.parent.mkdir(parents=True)
    notifications.write_text(
        json.dumps(
            {
                "id": "n1",
                "timestamp": "2026-05-08T12:00:00",
                "sender": "test",
                "action_data": {"agent_name": "a"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with patch.object(Path, "home", return_value=tmp_path):
        result = run_historical_auto_name_migration()

    assert result.migrated_names["a"] == "260508.a"
    assert result.migrated_names["b"] == "260508.b"
    assert result.migrated_names["b.1"] == "260508.b.1"
    assert result.migrated_names["c"] == "260508.c"
    assert result.migrated_names["c.plan"] == "260508.c.plan"
    assert _read_json(old / "agent_meta.json") == {
        "name": "260508.a",
        "workflow_name": "260508.a",
        "wait_for": ["260508.b", "sase-z"],
    }
    assert _read_json(dependent / "waiting.json") == {"waiting_for": ["260508.a"]}
    assert (dependent / "raw_xprompt.md").read_text(encoding="utf-8") == (
        "%w:260508.a\n#fork:260508.b.1 continue\n#resume:260508.b.1 legacy continue\n"
    )
    assert _read_json(bundle)["agent_name"] == "260508.c"
    migrated_history = _read_json(history)["prompts"]  # type: ignore[index]
    assert migrated_history[0]["text"] == (
        "%wait:260508.a,260508.c\n#fork(260508.b.1) run"
    )
    notification_line = notifications.read_text(encoding="utf-8").splitlines()[0]
    assert json.loads(notification_line)["action_data"]["agent_name"] == "260508.a"


def test_migrates_current_process_artifact_and_resets_auto_namespace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifacts_dir = _artifact(tmp_path, "20260508200053", {"name": "aoa"})
    monkeypatch.setenv("SASE_AGENT_NAME", "aoa")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))

    with patch.object(Path, "home", return_value=tmp_path):
        run_historical_auto_name_migration()
        assert get_next_auto_name() == "1"

    assert _read_json(artifacts_dir / "agent_meta.json")["name"] == "260508.aoa"


def test_migration_is_idempotent(tmp_path: Path) -> None:
    artifact_dir = _artifact(tmp_path, "20260508120000", {"name": "a"})

    with patch.object(Path, "home", return_value=tmp_path):
        first = run_historical_auto_name_migration()
        second = run_historical_auto_name_migration()

    assert first.changed is True
    assert second.skipped_by_marker is True
    assert _read_json(artifact_dir / "agent_meta.json")["name"] == "260508.a"


def test_migration_does_not_prefix_non_auto_user_name(tmp_path: Path) -> None:
    artifact_dir = _artifact(tmp_path, "20260508120000", {"name": "sase-z"})

    with patch.object(Path, "home", return_value=tmp_path):
        run_historical_auto_name_migration()

    assert _read_json(artifact_dir / "agent_meta.json")["name"] == "sase-z"


def test_migration_refreshes_artifact_index_and_dismissed_projection(
    tmp_path: Path,
) -> None:
    artifact_dir = _artifact(tmp_path, "20260508120000", {"name": "a"})
    bundle = tmp_path / ".sase" / "dismissed_bundles" / "202605" / "20260508121000.json"
    bundle.parent.mkdir(parents=True)
    bundle.write_text(
        json.dumps({"agent_name": "b", "workflow_name": "b"}),
        encoding="utf-8",
    )

    with (
        patch.object(Path, "home", return_value=tmp_path),
        patch(
            "sase.agent.names._migration.upsert_agent_artifact_index_artifacts"
        ) as mock_upsert,
        patch(
            "sase.agent.names._migration.sync_dismissed_agent_artifact_index"
        ) as mock_sync,
    ):
        run_historical_auto_name_migration()

    mock_upsert.assert_called_once()
    assert set(mock_upsert.call_args.args[0]) == {artifact_dir}
    mock_sync.assert_called_once_with(force=True)
