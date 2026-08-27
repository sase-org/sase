"""Tests for axe_run_agent artifact helper utilities."""

import json
from pathlib import Path
from unittest.mock import patch

from sase.agent.names import lookup_registered_name, rebuild_name_registry
from sase.axe.run_agent_helpers import (
    append_meta_list_field,
    create_followup_artifacts,
    promote_to_workflow,
    update_meta_field,
    update_meta_suffix,
)
from sase.plan_chain import (
    PLAN_CHAIN_PARENT_TIMESTAMP_FIELD,
    allocate_agent_family_child_suffix,
)


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

    with (
        patch(
            "sase.axe.run_agent_helpers.update_agent_artifact_index_for_marker_mutation",
            side_effect=lambda path: calls.append(path),
        ),
        patch(
            "sase.core.agent_artifact_index_lifecycle."
            "update_agent_artifact_index_for_marker_mutation",
            side_effect=lambda path: calls.append(str(path)),
        ),
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


def test_promote_to_workflow_renames_plan_root_to_first_member(tmp_path) -> None:
    meta_path = tmp_path / "agent_meta.json"
    meta_path.write_text(json.dumps({"name": "a", "pid": 123}))

    promote_to_workflow(str(tmp_path), "a")

    meta = json.loads(meta_path.read_text())
    assert meta["name"] == "a--plan"
    assert meta["workflow_name"] == "a"
    assert meta["plan_chain_root"] is True
    assert meta["agent_family"] == "a"
    assert meta["agent_family_role"] == "root"
    assert meta["role_suffix"] == "--plan"
    assert meta["pid"] == 123


def test_promote_to_workflow_ignores_preexisting_hood_neighbor_prefix(
    tmp_path: Path,
) -> None:
    artifacts_root = tmp_path / ".sase/projects/proj/artifacts/ace-run"
    root_dir = artifacts_root / "20260803082344"
    hood_dir = artifacts_root / "20260803082549"
    root_dir.mkdir(parents=True)
    hood_dir.mkdir(parents=True)
    (root_dir / "agent_meta.json").write_text(
        json.dumps({"name": "sq", "pid": 123}),
        encoding="utf-8",
    )
    (hood_dir / "agent_meta.json").write_text(
        json.dumps({"name": "sq.w0", "pid": 456}),
        encoding="utf-8",
    )

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        promote_to_workflow(str(root_dir), "sq")

        meta = json.loads((root_dir / "agent_meta.json").read_text(encoding="utf-8"))
        assert meta["name"] == "sq--plan"
        assert meta["agent_family"] == "sq"
        assert lookup_registered_name("sq")["container_kind"] == "family"


def test_promote_to_workflow_renames_generic_root_to_zero_member(tmp_path) -> None:
    meta_path = tmp_path / "agent_meta.json"
    meta_path.write_text(json.dumps({"name": "a", "pid": 123}))

    promote_to_workflow(str(tmp_path), "a", role_suffix="--0")

    meta = json.loads(meta_path.read_text())
    assert meta["name"] == "a--0"
    assert meta["workflow_name"] == "a"
    assert meta["agent_family"] == "a"
    assert meta["agent_family_role"] == "root"
    assert meta["role_suffix"] == "--0"


def test_promoted_plan_root_leaves_plan_zero_for_feedback_allocation(
    tmp_path: Path,
) -> None:
    artifact_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/20260701010101"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "agent_meta.json").write_text(json.dumps({"name": "a"}))

    with patch.object(Path, "home", return_value=tmp_path):
        promote_to_workflow(str(artifact_dir), "a")
        suffix = allocate_agent_family_child_suffix("a", "--plan-@")

    assert suffix == "--plan-0"


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


def test_create_followup_persists_custom_role_override(tmp_path) -> None:
    """Ambiguous numeric rows persist the caller's custom family role."""
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
            agent_family_role="reviewer",
        )

    meta = json.loads((tmp_path / "new" / "agent_meta.json").read_text())
    assert meta["name"] == "a--2"
    assert meta["agent_family"] == "a"
    assert meta["agent_family_role"] == "reviewer"
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


def test_create_followup_inherits_reasoning_effort(tmp_path) -> None:
    """Retry/follow-up agents preserve the parent's recorded effort."""
    new_dir = tmp_path / "new"
    new_dir.mkdir()

    with patch(
        "sase.axe.run_agent_helpers.create_artifacts_directory",
        return_value=str(new_dir),
    ):
        create_followup_artifacts(
            "proj",
            {"name": "a", "model": "test", "reasoning_effort": "xhigh"},
            "--1",
            "20260326120000",
        )

    meta = json.loads((new_dir / "agent_meta.json").read_text())
    assert meta["reasoning_effort"] == "xhigh"


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


def test_create_followup_artifacts_reserves_unique_timestamped_directories(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setattr(
        "sase.core.time.generate_timestamp",
        lambda: "260820_161407",
    )
    base_meta = {
        "name": "root--plan",
        "model": "opus",
        "workspace_dir": "/managed/ws/proj_7",
    }

    first = create_followup_artifacts(
        "test_proj",
        base_meta,
        "--plan-0",
        "20260820161400",
        workspace_num=7,
        agent_name_override="root--plan-0",
        workflow_name="root",
        relationships={
            "source_plan_agent_name": "root--plan",
            "feedback_submitted_at": "2026-08-20T16:14:07+00:00",
        },
    )
    second = create_followup_artifacts(
        "test_proj",
        base_meta,
        "--plan-1",
        "20260820161400",
        workspace_num=7,
        agent_name_override="root--plan-1",
        workflow_name="root",
        relationships={
            "source_plan_agent_name": "root--plan-0",
            "feedback_submitted_at": "2026-08-20T16:15:07+00:00",
        },
    )

    assert first != second
    assert Path(first).name == "20260820161407"
    assert Path(second).name == "20260820161408"

    first_meta = json.loads((Path(first) / "agent_meta.json").read_text())
    second_meta = json.loads((Path(second) / "agent_meta.json").read_text())

    assert first_meta["name"] == "root--plan-0"
    assert first_meta["role_suffix"] == "--plan-0"
    assert first_meta["source_plan_agent_name"] == "root--plan"
    assert first_meta["workspace_dir"] == "/managed/ws/proj_7"
    assert first_meta["workspace_num"] == 7

    assert second_meta["name"] == "root--plan-1"
    assert second_meta["role_suffix"] == "--plan-1"
    assert second_meta["source_plan_agent_name"] == "root--plan-0"
    assert second_meta["workspace_dir"] == first_meta["workspace_dir"]
    assert second_meta["workspace_num"] == first_meta["workspace_num"]
