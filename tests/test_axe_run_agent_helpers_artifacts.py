"""Tests for axe_run_agent artifact helper utilities."""

import json
from unittest.mock import patch

from sase.axe.run_agent_helpers import (
    append_meta_list_field,
    create_followup_artifacts,
    promote_to_workflow,
    update_meta_field,
    update_meta_suffix,
    write_episode_trace_marker,
)
from sase.plan_chain import PLAN_CHAIN_PARENT_TIMESTAMP_FIELD


def test_update_meta_field_sets_key(tmp_path) -> None:
    """update_meta_field reads, sets a key, and writes back."""
    meta_path = tmp_path / "agent_meta.json"
    meta_path.write_text(json.dumps({"pid": 123}))

    update_meta_field(str(tmp_path), "plan_submitted_at", "2025-06-15T10:05:00+00:00")

    meta = json.loads(meta_path.read_text())
    assert meta["plan_submitted_at"] == "2025-06-15T10:05:00+00:00"
    assert meta["pid"] == 123


def test_update_meta_field_missing_file(tmp_path) -> None:
    """update_meta_field is a no-op when agent_meta.json is missing."""
    update_meta_field(str(tmp_path), "key", "value")
    # No error raised, no file created
    assert not (tmp_path / "agent_meta.json").exists()


def test_meta_helpers_update_artifact_index_after_write(tmp_path) -> None:
    """agent_meta.json helper writes refresh the artifact index."""
    meta_path = tmp_path / "agent_meta.json"
    calls: list[str] = []

    with patch(
        "sase.axe.run_agent_helpers.update_agent_artifact_index_for_marker_mutation",
        side_effect=lambda path: calls.append(path),
    ):
        meta_path.write_text(json.dumps({"pid": 123}), encoding="utf-8")
        append_meta_list_field(str(tmp_path), "retry_started_at", "ts-1")

        meta_path.write_text(json.dumps({"pid": 123}), encoding="utf-8")
        update_meta_field(str(tmp_path), "plan_submitted_at", "ts-2")

        meta_path.write_text(json.dumps({"pid": 123}), encoding="utf-8")
        update_meta_suffix(str(tmp_path), ".code")

        meta_path.write_text(json.dumps({"name": "a", "pid": 123}), encoding="utf-8")
        promote_to_workflow(str(tmp_path), "a")

    assert calls == [str(tmp_path)] * 4


def test_promote_to_workflow_marks_stable_family_root(tmp_path) -> None:
    """promote_to_workflow keeps the root name stable and marks the family."""
    meta_path = tmp_path / "agent_meta.json"
    meta_path.write_text(json.dumps({"name": "a", "pid": 123}))

    promote_to_workflow(str(tmp_path), "a")

    meta = json.loads(meta_path.read_text())
    assert meta["name"] == "a"
    assert meta["workflow_name"] == "a"
    assert meta["plan_chain_root"] is True
    assert meta["agent_family"] == "a"
    assert meta["agent_family_role"] == "root"
    assert meta["role_suffix"] == "--plan"
    assert meta["pid"] == 123


def test_promote_to_workflow_can_promote_question_phase(tmp_path) -> None:
    """Question handoff roots record the question suffix without renaming."""
    meta_path = tmp_path / "agent_meta.json"
    meta_path.write_text(json.dumps({"name": "a", "pid": 123}))

    promote_to_workflow(str(tmp_path), "a", role_suffix=".q")

    meta = json.loads(meta_path.read_text())
    assert meta["name"] == "a"
    assert meta["workflow_name"] == "a"
    assert meta["agent_family"] == "a"
    assert meta["agent_family_role"] == "root"
    assert meta["role_suffix"] == "--q"


def test_create_followup_with_name_override(tmp_path) -> None:
    """agent_name_override replaces the inherited name in followup meta."""
    new_dir = tmp_path / "new"
    new_dir.mkdir()

    with patch(
        "sase.axe.run_agent_helpers.create_artifacts_directory",
        return_value=str(new_dir),
    ):
        create_followup_artifacts(
            "proj",
            {"name": "a", "model": "test"},
            ".code",
            "20260326120000",
            agent_name_override="a--code",
            workflow_name="a",
        )

    meta = json.loads((tmp_path / "new" / "agent_meta.json").read_text())
    assert meta["name"] == "a--code"
    assert meta["workflow_name"] == "a"
    assert meta["agent_family"] == "a"
    assert meta["agent_family_role"] == "code"
    assert meta["role_suffix"] == "--code"
    assert meta["parent_timestamp"] == "20260326120000"
    assert meta[PLAN_CHAIN_PARENT_TIMESTAMP_FIELD] == "20260326120000"


def test_create_followup_persists_root_question_role_override(tmp_path) -> None:
    """Ambiguous numeric root question rows persist agent_family_role='q'."""
    new_dir = tmp_path / "new"
    new_dir.mkdir()

    with patch(
        "sase.axe.run_agent_helpers.create_artifacts_directory",
        return_value=str(new_dir),
    ):
        create_followup_artifacts(
            "proj",
            {"name": "a", "model": "test"},
            "--2",
            "20260326120000",
            agent_name_override="a--2",
            workflow_name="a",
            agent_family_role="q",
        )

    meta = json.loads((tmp_path / "new" / "agent_meta.json").read_text())
    assert meta["name"] == "a--2"
    assert meta["agent_family"] == "a"
    assert meta["agent_family_role"] == "q"
    assert meta["role_suffix"] == "--2"


def test_create_followup_inherits_name_without_override(tmp_path) -> None:
    """Without agent_name_override, name is inherited from base_meta."""
    new_dir = tmp_path / "new"
    new_dir.mkdir()

    with patch(
        "sase.axe.run_agent_helpers.create_artifacts_directory",
        return_value=str(new_dir),
    ):
        create_followup_artifacts(
            "proj",
            {"name": "a", "model": "test"},
            ".code",
            "20260326120000",
        )

    meta = json.loads((tmp_path / "new" / "agent_meta.json").read_text())
    assert meta["name"] == "a"
    assert "workflow_name" not in meta


def test_create_followup_inherits_workspace_dir(tmp_path) -> None:
    """Follow-up agents inherit the parent's workspace_dir.

    Numbered-workspace follow-up children (the live-diff source) must persist
    the workspace they run in so the TUI can resolve the diff directly from
    agent_meta.json instead of re-deriving the path.
    """
    new_dir = tmp_path / "new"
    new_dir.mkdir()

    with patch(
        "sase.axe.run_agent_helpers.create_artifacts_directory",
        return_value=str(new_dir),
    ):
        create_followup_artifacts(
            "proj",
            {
                "name": "a",
                "model": "test",
                "workspace_dir": "/managed/ws/proj_3/",
            },
            ".code",
            "20260326120000",
            workspace_num=3,
        )

    meta = json.loads((new_dir / "agent_meta.json").read_text())
    assert meta["workspace_dir"] == "/managed/ws/proj_3/"
    assert meta["workspace_num"] == 3


def test_create_followup_without_workspace_dir_omits_key(tmp_path) -> None:
    """No workspace_dir in base_meta leaves the key absent (graceful)."""
    new_dir = tmp_path / "new"
    new_dir.mkdir()

    with patch(
        "sase.axe.run_agent_helpers.create_artifacts_directory",
        return_value=str(new_dir),
    ):
        create_followup_artifacts(
            "proj",
            {"name": "a", "model": "test"},
            ".code",
            "20260326120000",
            workspace_num=3,
        )

    meta = json.loads((new_dir / "agent_meta.json").read_text())
    assert "workspace_dir" not in meta


def test_create_followup_artifacts_updates_artifact_index(tmp_path) -> None:
    """Follow-up agent meta + workflow marker creation refreshes once."""
    followup = tmp_path / "followup"
    followup.mkdir()
    calls: list[str] = []

    with (
        patch(
            "sase.axe.run_agent_helpers.create_artifacts_directory",
            return_value=str(followup),
        ),
        patch(
            "sase.axe.run_agent_helpers.update_agent_artifact_index_for_marker_mutation",
            side_effect=lambda path: calls.append(path),
        ),
    ):
        create_followup_artifacts(
            "proj",
            {"name": "a", "model": "test"},
            ".code",
            "20260326120000",
        )

    assert calls == [str(followup)]
    assert (followup / "agent_meta.json").is_file()
    assert (followup / "workflow_state.json").is_file()


def test_create_followup_artifacts_writes_episode_trace(tmp_path) -> None:
    """Follow-up directories get lightweight episodic-memory linkage hints."""
    followup = tmp_path / "20260526120000"
    followup.mkdir()

    with patch(
        "sase.axe.run_agent_helpers.create_artifacts_directory",
        return_value=str(followup),
    ):
        create_followup_artifacts(
            "proj",
            {
                "name": "root",
                "model": "test",
                "changespec_name": "episode-cl",
                "phase_bead_id": "sase-45.6",
            },
            ".code",
            "20260526110000",
            agent_name_override="root--code",
            workflow_name="root",
        )

    trace = json.loads((followup / "episode_trace.json").read_text())
    assert trace["schema_version"] == 1
    assert trace["artifact_timestamp"] == "20260526120000"
    assert trace["agent_name"] == "root--code"
    assert trace["agent_family"] == "root"
    assert trace["agent_role"] == "code"
    assert trace["role_suffix"] == "--code"
    assert trace["parent_timestamp"] == "20260526110000"
    assert trace["changespec_names"] == ["episode-cl"]
    assert trace["bead_ids"] == ["sase-45.6"]


def test_write_episode_trace_marker_records_stable_paths(tmp_path) -> None:
    """The trace marker records only stable hints derived from artifacts."""
    (tmp_path / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "agent",
                "agent_family": "family",
                "role_suffix": "--plan",
                "plan_path": str(tmp_path / "plan.md"),
                "chat_path": str(tmp_path / "chat.md"),
                "changespec_name": "episode-cl",
                "bead_id": "sase-45",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "plan_feedback.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "qa_log.jsonl").write_text("{}\n", encoding="utf-8")

    changed = write_episode_trace_marker(
        str(tmp_path),
        root_timestamp="20260526100000",
    )

    assert changed is True
    trace = json.loads((tmp_path / "episode_trace.json").read_text())
    assert trace["chat_path"].endswith("chat.md")
    assert trace["plan_path"].endswith("plan.md")
    assert trace["feedback_paths"] == [str(tmp_path / "plan_feedback.jsonl")]
    assert trace["qa_paths"] == [str(tmp_path / "qa_log.jsonl")]
    assert trace["root_timestamp"] == "20260526100000"
