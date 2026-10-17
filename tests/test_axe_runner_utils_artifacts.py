"""Artifact marker and hidden-step tests for axe runner utils.

Split from ``tests.test_axe_runner_utils``; the original module re-exports
these tests so its import path keeps working.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.ace.agent_tribes import REVIEW_AGENT_TRIBE
from sase.axe.runner_artifacts import (
    all_steps_hidden,
    clear_agent_meta_tribe,
    detect_write_and_persist_review_agent_meta,
    write_done_marker,
)

__all__ = [
    "test_all_steps_hidden_all_hidden",
    "test_all_steps_hidden_empty_steps",
    "test_all_steps_hidden_missing_file",
    "test_all_steps_hidden_mixed",
    "test_all_steps_hidden_no_hidden_key",
    "test_all_steps_hidden_skipped_steps_ignored",
    "test_all_steps_hidden_visible_completed_step",
    "test_clear_agent_meta_tribe_removes_canonical_and_legacy_keys",
    "test_clear_agent_meta_tribe_safe_noops",
    "test_detect_write_and_persist_review_agent_meta",
    "test_write_done_marker_can_write_visible_review_agent",
]


def test_all_steps_hidden_all_hidden() -> None:
    """Test returns True when every step has hidden: true."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state = {
            "steps": [
                {"name": "a", "hidden": True},
                {"name": "b", "hidden": True},
            ]
        }
        with open(os.path.join(tmpdir, "workflow_state.json"), "w") as f:
            json.dump(state, f)
        assert all_steps_hidden(tmpdir) is True


def test_all_steps_hidden_mixed() -> None:
    """Test returns False when at least one step is visible."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state = {
            "steps": [
                {"name": "a", "hidden": True},
                {"name": "b", "hidden": False},
            ]
        }
        with open(os.path.join(tmpdir, "workflow_state.json"), "w") as f:
            json.dump(state, f)
        assert all_steps_hidden(tmpdir) is False


def test_all_steps_hidden_no_hidden_key() -> None:
    """Test returns False when steps lack hidden key (defaults to visible)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state = {"steps": [{"name": "a"}]}
        with open(os.path.join(tmpdir, "workflow_state.json"), "w") as f:
            json.dump(state, f)
        assert all_steps_hidden(tmpdir) is False


def test_all_steps_hidden_empty_steps() -> None:
    """Test returns False when steps list is empty."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state: dict[str, list[object]] = {"steps": []}
        with open(os.path.join(tmpdir, "workflow_state.json"), "w") as f:
            json.dump(state, f)
        assert all_steps_hidden(tmpdir) is False


def test_all_steps_hidden_missing_file() -> None:
    """Test returns False when workflow_state.json doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        assert all_steps_hidden(tmpdir) is False


def test_all_steps_hidden_skipped_steps_ignored() -> None:
    """Test returns True when non-hidden steps were all skipped."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state = {
            "steps": [
                {"name": "a", "hidden": True, "status": "completed"},
                {"name": "b", "hidden": False, "status": "skipped"},
            ]
        }
        with open(os.path.join(tmpdir, "workflow_state.json"), "w") as f:
            json.dump(state, f)
        assert all_steps_hidden(tmpdir) is True


def test_all_steps_hidden_visible_completed_step() -> None:
    """Test returns False when a non-hidden step actually ran."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state = {
            "steps": [
                {"name": "a", "hidden": True, "status": "completed"},
                {"name": "b", "hidden": False, "status": "completed"},
            ]
        }
        with open(os.path.join(tmpdir, "workflow_state.json"), "w") as f:
            json.dump(state, f)
        assert all_steps_hidden(tmpdir) is False


def test_write_done_marker_can_write_visible_review_agent() -> None:
    """Review agents should complete without forcing hidden rows."""
    with tempfile.TemporaryDirectory() as tmpdir:
        calls: list[str] = []
        with patch(
            "sase.core.agent_artifact_index_lifecycle."
            "update_agent_artifact_index_for_marker_mutation",
            side_effect=lambda path: calls.append(path),
        ):
            write_done_marker(
                tmpdir,
                cl_name="my_cl",
                project_file="/tmp/project.sase",
                timestamp="260506_120000",
                exit_code=0,
                hidden=False,
            )

        with open(os.path.join(tmpdir, "done.json"), encoding="utf-8") as f:
            data = json.load(f)

        assert data["outcome"] == "completed"
        assert data["artifacts_timestamp"] == "20260506120000"
        assert "hidden" not in data
        assert calls == [tmpdir]


def test_detect_write_and_persist_review_agent_meta(tmp_path: Path) -> None:
    """Specialized review runners persist the same tribe as tribe=review."""
    artifacts_dir = tmp_path / "crs" / "20260506120000"
    artifacts_dir.mkdir(parents=True)
    tribe_file = tmp_path / "agent_tribes.json"

    mock_provider = MagicMock()
    mock_provider.resolve_model_name.return_value = "test-model"
    calls: list[str] = []

    with (
        patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file),
        patch(
            "sase.llm_provider.registry.get_default_provider_name",
            return_value="test-provider",
        ),
        patch("sase.llm_provider.registry.get_provider", return_value=mock_provider),
        patch(
            "sase.workspace_provider.detect_workflow_type",
            return_value="git",
        ),
        patch("sase.workspace_provider.get_display_name", return_value="Git"),
        patch(
            "sase.core.agent_artifact_index_lifecycle."
            "update_agent_artifact_index_for_marker_mutation",
            side_effect=lambda path: calls.append(path),
        ),
    ):
        detect_write_and_persist_review_agent_meta(
            str(artifacts_dir),
            "/tmp/project.sase",
            "my_cl",
        )

    with open(artifacts_dir / "agent_meta.json", encoding="utf-8") as f:
        meta = json.load(f)
    with open(tribe_file, encoding="utf-8") as f:
        tribes = json.load(f)

    assert meta["tribe"] == REVIEW_AGENT_TRIBE
    assert tribes == [
        {
            "id": ["run", "my_cl", "20260506120000"],
            "tribe": REVIEW_AGENT_TRIBE,
        }
    ]
    assert calls == [str(artifacts_dir)]


def test_clear_agent_meta_tribe_removes_canonical_and_legacy_keys(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "agent" / "20260623120000"
    artifacts_dir.mkdir(parents=True)
    meta_path = artifacts_dir / "agent_meta.json"
    meta_path.write_text(
        json.dumps(
            {
                "name": "foo.bar",
                "tribe": "current",
                "tag": "legacy",
                "model": "test-model",
            }
        ),
        encoding="utf-8",
    )
    calls: list[str] = []

    with patch(
        "sase.core.agent_artifact_index_lifecycle."
        "update_agent_artifact_index_for_marker_mutation",
        side_effect=lambda path: calls.append(path),
    ):
        assert clear_agent_meta_tribe(str(artifacts_dir)) is True

    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    assert meta == {"name": "foo.bar", "model": "test-model"}
    assert calls == [str(artifacts_dir)]


def test_clear_agent_meta_tribe_safe_noops(tmp_path: Path) -> None:
    missing_dir = tmp_path / "missing"
    assert clear_agent_meta_tribe(str(missing_dir)) is False

    artifacts_dir = tmp_path / "agent"
    artifacts_dir.mkdir()
    meta_path = artifacts_dir / "agent_meta.json"
    meta_path.write_text(json.dumps({"name": "foo.bar"}), encoding="utf-8")
    assert clear_agent_meta_tribe(str(artifacts_dir)) is False
    assert json.loads(meta_path.read_text(encoding="utf-8")) == {"name": "foo.bar"}

    meta_path.write_text("{not-json", encoding="utf-8")
    assert clear_agent_meta_tribe(str(artifacts_dir)) is False
