"""Tests for extract_step_output_and_diff_path folding in commit result files."""

import json
from pathlib import Path

import pytest

from sase.axe.run_agent_helpers import extract_step_output_and_diff_path


def test_extract_step_output_preserves_multiline_commit_result_message(
    tmp_path: Path,
) -> None:
    state_data = {
        "workflow_name": "test",
        "status": "completed",
        "steps": [
            {
                "name": "step1",
                "status": "completed",
                "output": {"result": "ok"},
            }
        ],
    }
    full_message = "feat: add report\n\nInclude body details.\n\n- keep blanks"
    (tmp_path / "workflow_state.json").write_text(json.dumps(state_data))
    (tmp_path / "commit_result.json").write_text(
        json.dumps(
            {
                "message": full_message,
                "result": "abcdef1",
                "changespec_name": "sase-full-message",
                "cwd": "/workspace/sase-core_7",
            }
        )
    )

    step_output, diff_path = extract_step_output_and_diff_path(str(tmp_path))

    assert step_output is not None
    assert step_output["meta_commit_message"] == full_message
    assert step_output["meta_new_commit"] == "abcdef1"
    assert step_output["meta_commit_cwd"] == "/workspace/sase-core_7"
    assert step_output["meta_patch"] == "sase-full-message"
    assert step_output["meta_changespec"] == "sase-full-message"
    assert diff_path is None


def test_extract_step_output_reads_committed_at_from_single_commit_result(
    tmp_path: Path,
) -> None:
    state_data = {
        "workflow_name": "test",
        "status": "completed",
        "steps": [{"name": "step1", "status": "completed", "output": {"result": "ok"}}],
    }
    (tmp_path / "workflow_state.json").write_text(json.dumps(state_data))
    (tmp_path / "commit_result.json").write_text(
        json.dumps(
            {
                "message": "fix: linked",
                "result": "def4567",
                "cwd": "/workspace/sase-core_7",
                "committed_at": 1_700_000_000,
            }
        )
    )

    step_output, _diff_path = extract_step_output_and_diff_path(str(tmp_path))

    assert step_output is not None
    assert step_output["meta_commit_committed_at"] == "1700000000"


@pytest.mark.parametrize(
    "committed_at",
    [-1, True, "not-a-number", None],
)
def test_extract_step_output_drops_invalid_committed_at_on_single_commit_result(
    tmp_path: Path,
    committed_at: object,
) -> None:
    state_data = {
        "workflow_name": "test",
        "status": "completed",
        "steps": [{"name": "step1", "status": "completed", "output": {"result": "ok"}}],
    }
    (tmp_path / "workflow_state.json").write_text(json.dumps(state_data))
    (tmp_path / "commit_result.json").write_text(
        json.dumps(
            {
                "message": "fix: linked",
                "result": "def4567",
                "cwd": "/workspace/sase-core_7",
                "committed_at": committed_at,
            }
        )
    )

    step_output, _diff_path = extract_step_output_and_diff_path(str(tmp_path))

    assert step_output is not None
    assert "meta_commit_committed_at" not in step_output


def test_extract_step_output_surfaces_commit_results_list(
    tmp_path: Path,
) -> None:
    state_data = {
        "workflow_name": "test",
        "status": "completed",
        "steps": [
            {
                "name": "step1",
                "status": "completed",
                "output": {"result": "ok"},
            }
        ],
    }
    (tmp_path / "workflow_state.json").write_text(json.dumps(state_data))
    (tmp_path / "commit_result.json").write_text(
        json.dumps(
            {
                "message": "fix: linked",
                "result": "def4567",
                "cwd": "/workspace/sase-core_7",
                "diff_path": "/tmp/linked.diff",
            }
        )
    )
    (tmp_path / "commit_results.json").write_text(
        json.dumps(
            [
                {
                    "message": "fix: primary",
                    "result": "abcdef1",
                    "cwd": "/workspace/sase_7",
                    "patch_name": "sase-primary",
                    "diff_path": "/tmp/primary.diff",
                    "entry_id": "1",
                },
                {
                    "message": "fix: linked",
                    "result": "def4567",
                    "cwd": "/workspace/sase-core_7",
                    "repo_name": "sase-core",
                    "commit_changespec_name": "sase-linked",
                    "commit_diff_path": "/tmp/linked.diff",
                    "entry_id": "2",
                },
                {
                    "message": "chore: unattributed",
                    "result": "789abc0",
                    "cwd": "/workspace/tools_7",
                },
            ]
        )
    )

    step_output, diff_path = extract_step_output_and_diff_path(str(tmp_path))

    assert step_output is not None
    assert step_output["result"] == "ok"
    assert step_output["meta_commit_message"] == "fix: linked"
    assert step_output["meta_new_commit"] == "def4567"
    assert step_output["meta_commit_cwd"] == "/workspace/sase-core_7"
    assert step_output["meta_commits"] == [
        {
            "message": "fix: primary",
            "sha": "abcdef1",
            "cwd": "/workspace/sase_7",
            "patch_name": "sase-primary",
            "changespec_name": "sase-primary",
            "diff_path": "/tmp/primary.diff",
        },
        {
            "message": "fix: linked",
            "sha": "def4567",
            "cwd": "/workspace/sase-core_7",
            "repo_name": "sase-core",
            "patch_name": "sase-linked",
            "changespec_name": "sase-linked",
            "diff_path": "/tmp/linked.diff",
        },
        {
            "message": "chore: unattributed",
            "sha": "789abc0",
            "cwd": "/workspace/tools_7",
        },
    ]
    assert diff_path == "/tmp/linked.diff"


def test_extract_step_output_surfaces_committed_at_in_commits_list(
    tmp_path: Path,
) -> None:
    state_data = {
        "workflow_name": "test",
        "status": "completed",
        "steps": [{"name": "step1", "status": "completed", "output": {"result": "ok"}}],
    }
    (tmp_path / "workflow_state.json").write_text(json.dumps(state_data))
    (tmp_path / "commit_result.json").write_text(
        json.dumps(
            {"message": "fix: linked", "result": "def4567", "cwd": "/workspace-core"}
        )
    )
    (tmp_path / "commit_results.json").write_text(
        json.dumps(
            [
                {
                    "message": "fix: primary",
                    "result": "abcdef1",
                    "cwd": "/workspace-primary",
                    "committed_at": 1_700_000_000,
                },
                {
                    "message": "fix: linked",
                    "result": "def4567",
                    "cwd": "/workspace-core",
                    "committed_at": "not-a-number",
                },
            ]
        )
    )

    step_output, _diff_path = extract_step_output_and_diff_path(str(tmp_path))

    assert step_output is not None
    assert step_output["meta_commits"][0]["committed_at"] == "1700000000"
    assert "committed_at" not in step_output["meta_commits"][1]


def test_create_pull_request_projects_commit_sha_and_preserves_result_metadata(
    tmp_path: Path,
) -> None:
    state_data = {
        "workflow_name": "test",
        "status": "completed",
        "steps": [{"name": "step1", "status": "completed", "output": {}}],
    }
    sha = "a" * 40
    pr_url = "https://github.com/acme/project/pull/12"
    (tmp_path / "workflow_state.json").write_text(json.dumps(state_data))
    (tmp_path / "commit_result.json").write_text(
        json.dumps(
            {
                "method": "create_pull_request",
                "run_id": "run-12",
                "result": pr_url,
                "commit_sha": sha,
                "message": "feat: add change",
            }
        )
    )
    (tmp_path / "commit_results.json").write_text(
        json.dumps(
            [
                {
                    "method": "create_pull_request",
                    "run_id": "run-12",
                    "result": pr_url,
                    "commit_sha": sha,
                    "message": "feat: add change",
                },
                {
                    "method": "create_pull_request",
                    "run_id": "run-13",
                    "result": "https://github.com/acme/project/pull/13",
                },
            ]
        )
    )

    step_output, _diff_path = extract_step_output_and_diff_path(str(tmp_path))

    assert step_output is not None
    assert step_output["meta_new_commit"] == sha
    assert step_output["meta_commits"][0] == {
        "message": "feat: add change",
        "sha": sha,
        "commit_sha": sha,
        "method": "create_pull_request",
        "run_id": "run-12",
    }
    assert step_output["meta_commits"][1] == {
        "method": "create_pull_request",
        "run_id": "run-13",
    }
    assert pr_url not in str(step_output["meta_commits"])


def test_create_pull_request_without_commit_sha_does_not_project_pr_url(
    tmp_path: Path,
) -> None:
    (tmp_path / "commit_result.json").write_text(
        json.dumps(
            {
                "method": "create_pull_request",
                "result": "https://github.com/acme/project/pull/12",
            }
        )
    )

    step_output, _diff_path = extract_step_output_and_diff_path(str(tmp_path))

    # A PR URL alone is not commit metadata and must not create a commit record.
    assert step_output is None


def test_extract_step_output_prefers_commit_result_message_over_workflow_subject(
    tmp_path: Path,
) -> None:
    state_data = {
        "workflow_name": "test",
        "status": "completed",
        "steps": [
            {
                "name": "report",
                "status": "completed",
                "output": {
                    "meta_commit_message": "feat: add report",
                    "meta_pr_url": "https://github.com/org/repo/pull/7",
                },
            }
        ],
    }
    full_message = "feat: add report\n\nThis is the full commit body."
    (tmp_path / "workflow_state.json").write_text(json.dumps(state_data))
    (tmp_path / "commit_result.json").write_text(
        json.dumps({"message": full_message, "result": "abcdef1"})
    )

    step_output, _diff_path = extract_step_output_and_diff_path(str(tmp_path))

    assert step_output is not None
    assert step_output["meta_commit_message"] == full_message
    assert step_output["meta_pr_url"] == "https://github.com/org/repo/pull/7"
