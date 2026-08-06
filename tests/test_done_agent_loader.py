"""Tests for load_done_agents reading step_output from done.json."""

import json
from pathlib import Path

import pytest

from sase.ace.tui.models._loaders._done_loaders import (
    _build_done_agent_from_record,
    _load_done_agent_for_dir,
)
from sase.axe.run_agent_helpers import extract_step_output_and_diff_path
from sase.core.agent_scan_wire import AgentArtifactRecordWire, DoneMarkerWire


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
                "result": "abc123",
                "changespec_name": "sase-full-message",
                "cwd": "/workspace/sase-core_7",
            }
        )
    )

    step_output, diff_path = extract_step_output_and_diff_path(str(tmp_path))

    assert step_output is not None
    assert step_output["meta_commit_message"] == full_message
    assert step_output["meta_new_commit"] == "abc123"
    assert step_output["meta_commit_cwd"] == "/workspace/sase-core_7"
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
                "result": "def456",
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
                "result": "def456",
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
                "result": "def456",
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
                    "result": "abc123",
                    "cwd": "/workspace/sase_7",
                    "changespec_name": "sase-primary",
                    "diff_path": "/tmp/primary.diff",
                    "entry_id": "1",
                },
                {
                    "message": "fix: linked",
                    "result": "def456",
                    "cwd": "/workspace/sase-core_7",
                    "repo_name": "sase-core",
                    "commit_changespec_name": "sase-linked",
                    "commit_diff_path": "/tmp/linked.diff",
                    "entry_id": "2",
                },
                {
                    "message": "chore: unattributed",
                    "result": "789abc",
                    "cwd": "/workspace/tools_7",
                },
            ]
        )
    )

    step_output, diff_path = extract_step_output_and_diff_path(str(tmp_path))

    assert step_output is not None
    assert step_output["result"] == "ok"
    assert step_output["meta_commit_message"] == "fix: linked"
    assert step_output["meta_new_commit"] == "def456"
    assert step_output["meta_commit_cwd"] == "/workspace/sase-core_7"
    assert step_output["meta_commits"] == [
        {
            "message": "fix: primary",
            "sha": "abc123",
            "cwd": "/workspace/sase_7",
            "changespec_name": "sase-primary",
            "diff_path": "/tmp/primary.diff",
        },
        {
            "message": "fix: linked",
            "sha": "def456",
            "cwd": "/workspace/sase-core_7",
            "repo_name": "sase-core",
            "changespec_name": "sase-linked",
            "diff_path": "/tmp/linked.diff",
        },
        {
            "message": "chore: unattributed",
            "sha": "789abc",
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
            {"message": "fix: linked", "result": "def456", "cwd": "/workspace-core"}
        )
    )
    (tmp_path / "commit_results.json").write_text(
        json.dumps(
            [
                {
                    "message": "fix: primary",
                    "result": "abc123",
                    "cwd": "/workspace-primary",
                    "committed_at": 1_700_000_000,
                },
                {
                    "message": "fix: linked",
                    "result": "def456",
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
        json.dumps({"message": full_message, "result": "abc123"})
    )

    step_output, _diff_path = extract_step_output_and_diff_path(str(tmp_path))

    assert step_output is not None
    assert step_output["meta_commit_message"] == full_message
    assert step_output["meta_pr_url"] == "https://github.com/org/repo/pull/7"


def test_extract_diff_path_ignores_non_diff_path_typed_outputs(
    tmp_path: Path,
) -> None:
    """Arbitrary path-typed outputs are NOT diffs and must not be promoted.

    Regression for the #sshot crash: a step output with only generic
    ``"path"``-typed fields (e.g. a screenshot's ``local_path``) must yield
    ``diff_path is None`` instead of promoting the first path artifact.
    """
    state_data = {
        "workflow_name": "test",
        "status": "completed",
        "steps": [
            {
                "name": "fetch",
                "status": "completed",
                "output": {
                    "local_path": "/tmp/screenshots/shot.png",
                    "second_path": "/tmp/second.png",
                },
                "output_types": {"local_path": "path", "second_path": "path"},
            }
        ],
    }
    state_path = tmp_path / "workflow_state.json"
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state_data, f)

    step_output, diff_path = extract_step_output_and_diff_path(str(tmp_path))

    assert diff_path is None
    # The screenshot path is still preserved in the step output for display.
    assert step_output == {
        "local_path": "/tmp/screenshots/shot.png",
        "second_path": "/tmp/second.png",
    }


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
                    "project_file": "/home/user/.sase/projects/sase/sase.sase",
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


def test_done_agent_loader_backfills_commit_cwd_from_commit_result(
    tmp_path: Path,
) -> None:
    artifact_dir = tmp_path / "20260624120000"
    artifact_dir.mkdir()
    commit_cwd = tmp_path / "sase-core_7"
    (artifact_dir / "done.json").write_text(
        json.dumps(
            {
                "cl_name": "sase-test",
                "outcome": "completed",
                "project_file": str(tmp_path / "sase.sase"),
                "step_output": {
                    "meta_commit_message": "feat: linked",
                    "meta_new_commit": "abc123",
                },
            }
        ),
        encoding="utf-8",
    )
    (artifact_dir / "commit_result.json").write_text(
        json.dumps(
            {"message": "feat: linked", "result": "abc123", "cwd": str(commit_cwd)}
        ),
        encoding="utf-8",
    )

    agent = _load_done_agent_for_dir(artifact_dir, "ace-run", {}, {})

    assert agent is not None
    assert agent.step_output is not None
    assert agent.step_output["meta_commit_cwd"] == str(commit_cwd)
    assert agent.step_output["meta_commits"] == [
        {
            "message": "feat: linked",
            "sha": "abc123",
            "cwd": str(commit_cwd),
        }
    ]


def test_done_agent_loader_backfills_committed_at_into_single_commit(
    tmp_path: Path,
) -> None:
    artifact_dir = tmp_path / "20260624120015"
    artifact_dir.mkdir()
    commit_cwd = tmp_path / "sase-core_7"
    (artifact_dir / "done.json").write_text(
        json.dumps(
            {
                "cl_name": "sase-test",
                "outcome": "completed",
                "project_file": str(tmp_path / "sase.sase"),
                "step_output": {
                    "meta_commit_message": "feat: linked",
                    "meta_new_commit": "abc123",
                },
            }
        ),
        encoding="utf-8",
    )
    (artifact_dir / "commit_result.json").write_text(
        json.dumps(
            {
                "message": "feat: linked",
                "result": "abc123",
                "cwd": str(commit_cwd),
                "committed_at": 1_700_000_000,
            }
        ),
        encoding="utf-8",
    )

    agent = _load_done_agent_for_dir(artifact_dir, "ace-run", {}, {})

    assert agent is not None
    assert agent.step_output is not None
    assert agent.step_output["meta_commits"] == [
        {
            "message": "feat: linked",
            "sha": "abc123",
            "cwd": str(commit_cwd),
            "committed_at": "1700000000",
        }
    ]


def test_done_agent_loader_backfills_commit_results_list(
    tmp_path: Path,
) -> None:
    artifact_dir = tmp_path / "20260624120030"
    artifact_dir.mkdir()
    linked_cwd = tmp_path / "sase-core_7"
    (artifact_dir / "done.json").write_text(
        json.dumps(
            {
                "cl_name": "sase-test",
                "outcome": "completed",
                "project_file": str(tmp_path / "sase.sase"),
                "step_output": {
                    "meta_commit_message": "feat: linked",
                    "meta_new_commit": "def456",
                },
            }
        ),
        encoding="utf-8",
    )
    (artifact_dir / "commit_result.json").write_text(
        json.dumps(
            {"message": "feat: linked", "result": "def456", "cwd": str(linked_cwd)}
        ),
        encoding="utf-8",
    )
    (artifact_dir / "commit_results.json").write_text(
        json.dumps(
            [
                {
                    "message": "feat: primary",
                    "result": "abc123",
                    "cwd": str(tmp_path / "sase_7"),
                },
                {
                    "message": "feat: linked",
                    "result": "def456",
                    "cwd": str(linked_cwd),
                },
            ]
        ),
        encoding="utf-8",
    )

    agent = _load_done_agent_for_dir(artifact_dir, "ace-run", {}, {})

    assert agent is not None
    assert agent.step_output is not None
    assert agent.step_output["meta_commit_cwd"] == str(linked_cwd)
    assert agent.step_output["meta_commits"] == [
        {
            "message": "feat: primary",
            "sha": "abc123",
            "cwd": str(tmp_path / "sase_7"),
        },
        {
            "message": "feat: linked",
            "sha": "def456",
            "cwd": str(linked_cwd),
        },
    ]


def test_done_agent_loader_hydrates_sdd_commits_without_primary_meta(
    tmp_path: Path,
) -> None:
    artifact_dir = tmp_path / "20260624120045"
    artifact_dir.mkdir()
    sdd_cwd = tmp_path / "sase_7" / ".sase" / "sdd"
    (artifact_dir / "done.json").write_text(
        json.dumps(
            {
                "cl_name": "sase-test",
                "outcome": "completed",
                "project_file": str(tmp_path / "sase.sase"),
                "step_output": {"result": "ok"},
            }
        ),
        encoding="utf-8",
    )
    (artifact_dir / "commit_results.json").write_text(
        json.dumps(
            [
                {
                    "message": "Archive approved plan demo",
                    "result": "abc123",
                    "cwd": str(sdd_cwd),
                    "repo_name": "sase-org/sase--sdd",
                }
            ]
        ),
        encoding="utf-8",
    )

    agent = _load_done_agent_for_dir(artifact_dir, "ace-run", {}, {})

    assert agent is not None
    assert agent.step_output is not None
    assert agent.step_output["meta_commits"] == [
        {
            "message": "Archive approved plan demo",
            "sha": "abc123",
            "cwd": str(sdd_cwd),
            "repo_name": "sase-org/sase--sdd",
        }
    ]


def test_done_agent_loader_hydrates_sdd_commits_without_step_output(
    tmp_path: Path,
) -> None:
    artifact_dir = tmp_path / "20260624120050"
    artifact_dir.mkdir()
    (artifact_dir / "done.json").write_text(
        json.dumps(
            {
                "cl_name": "sase-test",
                "outcome": "completed",
                "project_file": str(tmp_path / "sase.sase"),
            }
        ),
        encoding="utf-8",
    )
    (artifact_dir / "commit_results.json").write_text(
        json.dumps(
            [
                {
                    "message": "Archive approved plan demo",
                    "result": "abc123",
                    "cwd": "/workspace/sase/.sase/sdd",
                    "repo_name": "sase-org/sase--sdd",
                }
            ]
        ),
        encoding="utf-8",
    )

    agent = _load_done_agent_for_dir(artifact_dir, "ace-run", {}, {})

    assert agent is not None
    assert agent.step_output == {
        "meta_commits": [
            {
                "message": "Archive approved plan demo",
                "sha": "abc123",
                "cwd": "/workspace/sase/.sase/sdd",
                "repo_name": "sase-org/sase--sdd",
            }
        ]
    }


def test_done_agent_loader_keeps_existing_commit_cwd(
    tmp_path: Path,
) -> None:
    artifact_dir = tmp_path / "20260624120100"
    artifact_dir.mkdir()
    (artifact_dir / "done.json").write_text(
        json.dumps(
            {
                "cl_name": "sase-test",
                "outcome": "completed",
                "project_file": str(tmp_path / "sase.sase"),
                "step_output": {
                    "meta_commit_message": "feat: linked",
                    "meta_new_commit": "abc123",
                    "meta_commit_cwd": "/kept",
                },
            }
        ),
        encoding="utf-8",
    )
    (artifact_dir / "commit_result.json").write_text(
        json.dumps({"cwd": "/ignored"}),
        encoding="utf-8",
    )

    agent = _load_done_agent_for_dir(artifact_dir, "ace-run", {}, {})

    assert agent is not None
    assert agent.step_output is not None
    assert agent.step_output["meta_commit_cwd"] == "/kept"


def test_done_agent_loader_merges_existing_meta_commits(
    tmp_path: Path,
) -> None:
    artifact_dir = tmp_path / "20260624120130"
    artifact_dir.mkdir()
    existing_commits = [{"message": "feat: kept", "sha": "111aaa", "cwd": "/kept"}]
    (artifact_dir / "done.json").write_text(
        json.dumps(
            {
                "cl_name": "sase-test",
                "outcome": "completed",
                "project_file": str(tmp_path / "sase.sase"),
                "step_output": {
                    "meta_commit_message": "feat: kept",
                    "meta_new_commit": "111aaa",
                    "meta_commit_cwd": "/kept",
                    "meta_commits": existing_commits,
                },
            }
        ),
        encoding="utf-8",
    )
    (artifact_dir / "commit_results.json").write_text(
        json.dumps(
            [{"message": "feat: ignored", "result": "222bbb", "cwd": "/ignored"}]
        ),
        encoding="utf-8",
    )

    agent = _load_done_agent_for_dir(artifact_dir, "ace-run", {}, {})

    assert agent is not None
    assert agent.step_output is not None
    assert agent.step_output["meta_commits"] == [
        {"message": "feat: kept", "sha": "111aaa", "cwd": "/kept"},
        {"message": "feat: ignored", "sha": "222bbb", "cwd": "/ignored"},
    ]


def test_done_agent_snapshot_loader_backfills_commit_cwd(
    tmp_path: Path,
) -> None:
    artifact_dir = tmp_path / "20260624120200"
    artifact_dir.mkdir()
    (artifact_dir / "commit_result.json").write_text(
        json.dumps({"message": "fix: linked", "result": "def456", "cwd": "/linked"}),
        encoding="utf-8",
    )
    record = AgentArtifactRecordWire(
        project_name="sase",
        project_dir=str(tmp_path),
        project_file=str(tmp_path / "sase.sase"),
        workflow_dir_name="ace-run",
        artifact_dir=str(artifact_dir),
        timestamp="20260624120200",
        done=DoneMarkerWire(
            outcome="completed",
            cl_name="sase-test",
            project_file=str(tmp_path / "sase.sase"),
            step_output={
                "meta_commit_message": "fix: linked",
                "meta_new_commit": "def456",
            },
        ),
        has_done_marker=True,
    )

    agent = _build_done_agent_from_record(record, {}, {})

    assert agent is not None
    assert agent.step_output is not None
    assert agent.step_output["meta_commit_cwd"] == "/linked"
    assert agent.step_output["meta_commits"] == [
        {"message": "fix: linked", "sha": "def456", "cwd": "/linked"}
    ]
