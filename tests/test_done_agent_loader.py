"""Tests for load_done_agents reading step_output from done.json."""

import json
from pathlib import Path

from sase.ace.tui.models._loaders._done_loaders import (
    _build_done_agent_from_record,
    _load_done_agent_for_dir,
)
from sase.core.agent_scan_wire import AgentArtifactRecordWire, DoneMarkerWire


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
