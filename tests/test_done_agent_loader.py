"""Tests for load_done_agents reading step_output from done.json."""

import json
from pathlib import Path
from unittest.mock import patch

from sase.axe.run_agent_helpers import extract_step_output_and_diff_path
from sase.ace.tui.models._loaders import load_done_agents


def test_extract_step_output_from_workflow_state(tmp_path: Path) -> None:
    """Verify extract_step_output_and_diff_path reads workflow_state.json."""
    state_data = {
        "workflow_name": "test",
        "status": "completed",
        "steps": [
            {
                "name": "step1",
                "status": "completed",
                "output": {"meta_id": "abc123", "result": "ok"},
                "output_types": {"meta_id": "text", "result": "text"},
            }
        ],
    }
    state_path = tmp_path / "workflow_state.json"
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state_data, f)

    step_output, diff_path = extract_step_output_and_diff_path(str(tmp_path))

    assert step_output == {"meta_id": "abc123", "result": "ok"}
    assert diff_path is None


def test_extract_diff_path_last_step_multiple_paths_first_wins(
    tmp_path: Path,
) -> None:
    """Verify first path-typed output wins when last step has multiple."""
    state_data = {
        "workflow_name": "test",
        "status": "completed",
        "steps": [
            {
                "name": "step1",
                "status": "completed",
                "output": {
                    "first_path": "/tmp/first.patch",
                    "second_path": "/tmp/second.patch",
                },
                "output_types": {"first_path": "path", "second_path": "path"},
            }
        ],
    }
    state_path = tmp_path / "workflow_state.json"
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state_data, f)

    _step_output, diff_path = extract_step_output_and_diff_path(str(tmp_path))

    assert diff_path == "/tmp/first.patch"


def test_extract_diff_path_fallback_to_direct_key(tmp_path: Path) -> None:
    """Verify diff_path fallback reads direct diff_path key from last step output."""
    state_data = {
        "workflow_name": "test",
        "status": "completed",
        "steps": [
            {
                "name": "step1",
                "status": "completed",
                "output": {"diff_path": "/tmp/changes.diff"},
            }
        ],
    }
    state_path = tmp_path / "workflow_state.json"
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state_data, f)

    _step_output, diff_path = extract_step_output_and_diff_path(str(tmp_path))

    assert diff_path == "/tmp/changes.diff"


def test_extract_diff_path_from_non_last_step(tmp_path: Path) -> None:
    """diff_path found in a middle step when later steps have no diff_path.

    Simulates #gh + #pr embedded workflows where gh.diff produces
    diff_path but the pr post-steps (create_changespec, create_pr,
    update_cl) come after it.
    """
    state_data = {
        "workflow_name": "anonymous",
        "status": "completed",
        "steps": [
            {
                "name": "gh.diff",
                "status": "completed",
                "output": {
                    "diff_path": "/tmp/sase-gh-abc123.diff",
                    "meta_commit_message": "feat: add feature",
                },
                "output_types": {"diff_path": "path", "meta_commit_message": "text"},
            },
            {
                "name": "pr.create_changespec",
                "status": "completed",
                "output": {
                    "success": True,
                    "cl_name": "my_cl",
                    "project_file": "/home/user/.sase/projects/sase/sase.gp",
                },
                "output_types": {
                    "success": "bool",
                    "cl_name": "word",
                    "project_file": "path",
                },
                "hidden": True,
            },
            {
                "name": "pr.update_cl",
                "status": "completed",
                "output": {
                    "updated": True,
                    "pr_url": "https://github.com/org/repo/pull/5",
                    "meta_new_pr": "https://github.com/org/repo/pull/5",
                },
                "output_types": {
                    "updated": "bool",
                    "pr_url": "line",
                    "meta_new_pr": "line",
                },
                "hidden": True,
            },
        ],
    }
    state_path = tmp_path / "workflow_state.json"
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state_data, f)

    step_output, diff_path = extract_step_output_and_diff_path(str(tmp_path))

    assert diff_path == "/tmp/sase-gh-abc123.diff"
    # step_output comes from the last step with a dict output
    assert step_output is not None
    assert step_output.get("meta_new_pr") == "https://github.com/org/repo/pull/5"


def test_extract_returns_none_without_workflow_state(tmp_path: Path) -> None:
    """Verify graceful handling when workflow_state.json doesn't exist."""
    step_output, diff_path = extract_step_output_and_diff_path(str(tmp_path))

    assert step_output is None
    assert diff_path is None


def test_load_done_agents_infers_image_from_saved_binary_diff(
    tmp_path: Path,
) -> None:
    """Done agents recover image attachments when done.json omitted them."""
    home = tmp_path / "home"
    artifact_dir = (
        home
        / ".sase"
        / "projects"
        / "proj"
        / "artifacts"
        / "ace-run"
        / "20260430032430"
    )
    artifact_dir.mkdir(parents=True)
    workspace = tmp_path / "workspace"
    image = workspace / "docs" / "images" / "panel.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"png")
    diff_path = tmp_path / "saved.diff"
    diff_path.write_text(
        "diff --git a/docs/images/panel.png b/docs/images/panel.png\n"
        "new file mode 100644\n"
        "Binary files /dev/null and b/docs/images/panel.png differ\n",
        encoding="utf-8",
    )
    plan_path = str(tmp_path / "plan.md")
    (artifact_dir / "done.json").write_text(
        json.dumps(
            {
                "cl_name": "feature",
                "project_file": str(home / ".sase" / "projects" / "proj" / "proj.gp"),
                "workspace_num": 101,
                "diff_path": str(diff_path),
                "plan_path": plan_path,
                "image_paths": [],
            }
        )
    )

    with (
        patch(
            "sase.ace.tui.models._loaders._done_loaders.Path.home",
            return_value=home,
        ),
        patch(
            "sase.ace.tui.models._loaders._image_attachments._resolve_workspace_dir",
            return_value=str(workspace),
        ),
    ):
        agents = load_done_agents({}, {})

    assert len(agents) == 1
    assert agents[0].extra_files == [plan_path, str(image.resolve())]
