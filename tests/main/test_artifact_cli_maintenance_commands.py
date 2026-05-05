"""Tests for ``sase artifact`` rebuild, doctor, and error handling commands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from sase.core.artifact_wire import (
    ARTIFACT_WIRE_SCHEMA_VERSION,
    ArtifactDoctorIssueWire,
    ArtifactDoctorOptionsWire,
    ArtifactDoctorWire,
    ArtifactMutationResultWire,
    ArtifactRebuildRequestWire,
)
from sase.main import artifact_handler
from sase.main.parser import create_parser


def test_rebuild_json_calls_facade_with_request(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    result = ArtifactMutationResultWire(
        schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
        operation="rebuild",
    )
    mock_builder = Mock(
        return_value=ArtifactRebuildRequestWire(
            projects_root="/projects",
            include_sources=("directory",),
        )
    )
    mock_rebuild = Mock(return_value=result)
    monkeypatch.setattr(
        artifact_handler.artifact_facade,
        "artifact_rebuild_request",
        mock_builder,
    )
    monkeypatch.setattr(
        artifact_handler.artifact_facade,
        "artifact_rebuild",
        mock_rebuild,
    )
    args = create_parser().parse_args(
        [
            "artifact",
            "rebuild",
            "-j",
            "-i",
            str(tmp_path / "graph.sqlite"),
            "-p",
            "/projects",
            "-w",
            "/workspace",
            "-b",
            "/beads",
            "-S",
            "directory",
            "-X",
            "agent_artifact",
            "-t",
            "/workspace/a.py",
            "-a",
            "/artifacts/run",
            "-c",
            "mark",
        ]
    )

    with pytest.raises(SystemExit) as exc_info:
        artifact_handler.handle_artifact_command(args)

    assert exc_info.value.code == 0
    mock_builder.assert_called_once_with(
        projects_root="/projects",
        workspace_root="/workspace",
        beads_dir="/beads",
        include_sources=("directory",),
        exclude_sources=("agent_artifact",),
        target_path="/workspace/a.py",
        artifact_dir="/artifacts/run",
        stale_cleanup="mark",
    )
    mock_rebuild.assert_called_once_with(
        tmp_path / "graph.sqlite",
        mock_builder.return_value,
    )
    assert json.loads(capsys.readouterr().out)["operation"] == "rebuild"


def test_rebuild_human_outputs_mutation_counts_and_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    result = ArtifactMutationResultWire(
        schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
        operation="rebuild",
        nodes_added=2,
        links_updated=1,
        tombstones_added=1,
        affected_node_ids=["note:1"],
        errors=["skipped unreadable source"],
    )
    monkeypatch.setattr(
        artifact_handler.artifact_facade,
        "artifact_rebuild_request",
        Mock(return_value=ArtifactRebuildRequestWire()),
    )
    monkeypatch.setattr(
        artifact_handler.artifact_facade,
        "artifact_rebuild",
        Mock(return_value=result),
    )
    args = create_parser().parse_args(
        ["artifact", "rebuild", "-i", str(tmp_path / "graph.sqlite")]
    )

    with pytest.raises(SystemExit) as exc_info:
        artifact_handler.handle_artifact_command(args)

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "operation: rebuild" in output
    assert "nodes +2 ~0 -0" in output
    assert "tombstones +1" in output
    assert "affected nodes: note:1" in output
    assert "skipped unreadable source" in output


def test_doctor_json_calls_facade(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    doctor = {"schema_version": ARTIFACT_WIRE_SCHEMA_VERSION, "ok": True, "issues": []}
    mock_doctor = Mock(return_value=doctor)
    monkeypatch.setattr(
        artifact_handler.artifact_facade, "artifact_doctor", mock_doctor
    )
    args = create_parser().parse_args(
        ["artifact", "doctor", "-j", "-i", str(tmp_path / "graph.sqlite")]
    )

    with pytest.raises(SystemExit) as exc_info:
        artifact_handler.handle_artifact_command(args)

    assert exc_info.value.code == 0
    mock_doctor.assert_called_once_with(
        tmp_path / "graph.sqlite",
        ArtifactDoctorOptionsWire(),
    )
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_doctor_human_exits_nonzero_when_issues_returned(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    doctor = ArtifactDoctorWire(
        schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
        ok=False,
        issues=[
            ArtifactDoctorIssueWire(
                issue_type="dangling_link",
                severity="error",
                artifact_id="note:1",
                link_id="link-1",
                message="link target is missing",
            )
        ],
    )
    monkeypatch.setattr(
        artifact_handler.artifact_facade,
        "artifact_doctor",
        Mock(return_value=doctor),
    )
    args = create_parser().parse_args(
        ["artifact", "doctor", "-i", str(tmp_path / "graph.sqlite")]
    )

    with pytest.raises(SystemExit) as exc_info:
        artifact_handler.handle_artifact_command(args)

    assert exc_info.value.code == 1
    output = capsys.readouterr().out
    assert "status: FAIL" in output
    assert "dangling_link" in output
    assert "link target is missing" in output


def test_doctor_json_exits_nonzero_when_issues_returned(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    doctor = ArtifactDoctorWire(
        schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
        ok=False,
        issues=[
            ArtifactDoctorIssueWire(
                issue_type="missing_root",
                severity="error",
                message="root is missing",
            )
        ],
    )
    monkeypatch.setattr(
        artifact_handler.artifact_facade,
        "artifact_doctor",
        Mock(return_value=doctor),
    )
    args = create_parser().parse_args(
        ["artifact", "doctor", "-j", "-i", str(tmp_path / "graph.sqlite")]
    )

    with pytest.raises(SystemExit) as exc_info:
        artifact_handler.handle_artifact_command(args)

    assert exc_info.value.code == 1
    assert json.loads(capsys.readouterr().out)["issues"][0]["issue_type"] == (
        "missing_root"
    )


def test_default_index_path_uses_patched_home_without_touching_real_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    mock_list = Mock(return_value=[])
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(artifact_handler.artifact_facade, "artifact_list", mock_list)
    args = create_parser().parse_args(["artifact", "list", "-j"])

    with pytest.raises(SystemExit) as exc_info:
        artifact_handler.handle_artifact_command(args)

    assert exc_info.value.code == 0
    assert mock_list.call_args.args[0] == home / ".sase" / "artifacts.sqlite"
    assert not (home / ".sase").exists()


def test_add_rejects_malformed_metadata_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = create_parser().parse_args(
        ["artifact", "add", "-a", "note:1", "-k", "note", "-m", "{"]
    )

    with pytest.raises(SystemExit) as exc_info:
        artifact_handler.handle_artifact_command(args)

    assert exc_info.value.code == 1
    assert "malformed metadata JSON" in capsys.readouterr().err


def test_add_rejects_malformed_compact_link_tuple(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = create_parser().parse_args(["artifact", "add", "-l", "parent|note:1"])

    with pytest.raises(SystemExit) as exc_info:
        artifact_handler.handle_artifact_command(args)

    assert exc_info.value.code == 1
    assert "compact link must be" in capsys.readouterr().err


def test_remove_rejects_incomplete_link_tuple(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = create_parser().parse_args(["artifact", "remove", "-T", "related"])

    with pytest.raises(SystemExit) as exc_info:
        artifact_handler.handle_artifact_command(args)

    assert exc_info.value.code == 1
    assert "link tuple removal requires" in capsys.readouterr().err


def test_facade_exception_reports_to_stderr_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        artifact_handler.artifact_facade,
        "artifact_list",
        Mock(side_effect=RuntimeError("index is unreadable")),
    )
    args = create_parser().parse_args(["artifact", "list"])

    with pytest.raises(SystemExit) as exc_info:
        artifact_handler.handle_artifact_command(args)

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "index is unreadable" in captured.err
