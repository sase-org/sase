"""Sync tests for ``sase artifact`` against the Rust extension."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.core.artifact_wire import (
    ARTIFACT_FILE_TYPE_CHAT,
    ARTIFACT_FILE_TYPE_DIFF,
    ARTIFACT_FILE_TYPE_METADATA_KEY,
    ARTIFACT_FILE_TYPE_MISC,
    ARTIFACT_FILE_TYPE_PLAN,
    ARTIFACT_FILE_TYPE_PROJECT,
    ARTIFACT_FILE_TYPE_PROMPT,
)
from sase.core.rust import RUST_EXTENSION_MODULE_NAME

from tests.main.artifact_cli_helpers import run_entry


def test_artifact_cli_real_extension_sync_file_types_and_directory_invariants(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    required = {
        "artifact_add",
        "artifact_rebuild",
        "artifact_list",
        "artifact_show",
        "artifact_doctor",
    }
    missing = sorted(name for name in required if not hasattr(rust_module, name))
    if missing:
        pytest.skip(f"sase_core_rs is too old: missing {missing}")

    index_path = tmp_path / "artifacts.sqlite"
    projects_root = tmp_path / "projects"
    project_dir = projects_root / "acme"
    project_file = project_dir / "acme.gp"
    workspace_root = tmp_path / "workspace"
    beads_dir = workspace_root / "sdd" / "beads"
    empty_directory = workspace_root / "empty-only"
    artifact_dir = project_dir / "artifacts" / "ace-run" / "20260505120000"
    loose_project_file = tmp_path / "loose" / "project-snapshot.gp"
    diff_path = artifact_dir / "commit.diff"
    plan_path = artifact_dir / "plan.md"
    response_path = artifact_dir / "response.md"
    prompt_path = artifact_dir / "raw_xprompt.md"
    misc_path = artifact_dir / "notes.txt"
    legacy_file = tmp_path / "legacy" / "old.log"

    for path in (
        project_file,
        loose_project_file,
        diff_path,
        plan_path,
        response_path,
        prompt_path,
        misc_path,
        legacy_file,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{path.name}\n", encoding="utf-8")
    beads_dir.mkdir(parents=True)
    empty_directory.mkdir(parents=True)
    project_file.write_text(
        "NAME: cl-one\nDESCRIPTION: Migration fixture\nSTATUS: WIP\n",
        encoding="utf-8",
    )
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "agent-alpha",
                "artifact_agent_id": "agent-alpha",
                "changespec_name": "cl-one",
                "llm_provider": "codex",
                "file_paths": [str(loose_project_file), str(misc_path)],
            }
        ),
        encoding="utf-8",
    )
    (artifact_dir / "done.json").write_text(
        json.dumps(
            {
                "name": "agent-alpha",
                "cl_name": "cl-one",
                "diff_path": str(diff_path),
                "plan_path": str(plan_path),
                "response_path": str(response_path),
            }
        ),
        encoding="utf-8",
    )

    code, output, error = run_entry(
        monkeypatch,
        capsys,
        "artifact",
        "add",
        "-j",
        "-i",
        str(index_path),
        "-a",
        str(legacy_file),
        "-k",
        "file",
        "-t",
        "old.log",
        "-q",
        "legacy misc file",
        "-l",
        f"parent|{legacy_file}|/",
    )
    assert (code, error) == (0, "")
    assert json.loads(output)["affected_node_ids"] == [str(legacy_file)]

    code, output, error = run_entry(
        monkeypatch,
        capsys,
        "artifact",
        "sync",
        "-j",
        "-i",
        str(index_path),
        "-p",
        str(projects_root),
        "-w",
        str(workspace_root),
        "-b",
        str(beads_dir),
    )
    sync = json.loads(output)
    assert (code, error) == (0, "")
    assert sync["operation"] == "rebuild"
    assert sync["errors"] == []

    expected_types = {
        diff_path: ARTIFACT_FILE_TYPE_DIFF,
        plan_path: ARTIFACT_FILE_TYPE_PLAN,
        response_path: ARTIFACT_FILE_TYPE_CHAT,
        prompt_path: ARTIFACT_FILE_TYPE_PROMPT,
        loose_project_file: ARTIFACT_FILE_TYPE_PROJECT,
        misc_path: ARTIFACT_FILE_TYPE_MISC,
    }
    for path, file_type in expected_types.items():
        code, output, error = run_entry(
            monkeypatch,
            capsys,
            "artifact",
            "show",
            "-j",
            "-i",
            str(index_path),
            "-a",
            str(path),
        )
        detail = json.loads(output)
        metadata = detail["node"]["metadata"]
        assert (code, error) == (0, "")
        assert metadata[ARTIFACT_FILE_TYPE_METADATA_KEY] == file_type
        assert "file_type" not in metadata

    buckets = {
        ARTIFACT_FILE_TYPE_PLAN: {str(plan_path)},
        ARTIFACT_FILE_TYPE_DIFF: {str(diff_path)},
        ARTIFACT_FILE_TYPE_CHAT: {str(response_path)},
        ARTIFACT_FILE_TYPE_PROJECT: {str(loose_project_file)},
        ARTIFACT_FILE_TYPE_PROMPT: {str(prompt_path)},
        ARTIFACT_FILE_TYPE_MISC: {str(misc_path), str(legacy_file)},
    }
    for file_type, expected_ids in buckets.items():
        code, output, error = run_entry(
            monkeypatch,
            capsys,
            "artifact",
            "list",
            "-j",
            "-i",
            str(index_path),
            "-F",
            file_type,
            "-l",
            "50",
        )
        ids = {node["id"] for node in json.loads(output)}
        assert (code, error) == (0, "")
        assert expected_ids <= ids

    code, output, error = run_entry(
        monkeypatch,
        capsys,
        "artifact",
        "show",
        "-j",
        "-i",
        str(index_path),
        "-a",
        str(empty_directory),
    )
    assert (code, error) == (0, "")
    assert json.loads(output)["node"] is None

    code, output, error = run_entry(
        monkeypatch,
        capsys,
        "artifact",
        "doctor",
        "-j",
        "-i",
        str(index_path),
    )
    assert (code, error) == (0, "")
    assert json.loads(output)["ok"] is True

    code, output, error = run_entry(
        monkeypatch,
        capsys,
        "artifact",
        "add",
        "-j",
        "-i",
        str(index_path),
        "-a",
        "manual-empty-dir",
        "-k",
        "directory",
        "-t",
        "manual-empty-dir",
        "-l",
        "parent|manual-empty-dir|/",
    )
    assert (code, error) == (0, "")

    code, output, error = run_entry(
        monkeypatch,
        capsys,
        "artifact",
        "doctor",
        "-j",
        "-i",
        str(index_path),
    )
    doctor = json.loads(output)
    assert (code, error) == (1, "")
    assert any(
        issue["issue_type"] == "orphan_directory"
        and issue["artifact_id"] == "manual-empty-dir"
        for issue in doctor["issues"]
    )
