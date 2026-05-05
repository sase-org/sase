"""Tests for the ``sase artifact`` CLI parser and JSON handlers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from sase.core.artifact_wire import (
    ARTIFACT_ROOT_ID,
    ARTIFACT_WIRE_SCHEMA_VERSION,
    ArtifactDoctorOptionsWire,
    ArtifactGraphOptionsWire,
    ArtifactMutationResultWire,
    ArtifactNodeWire,
    ArtifactQueryWire,
    ArtifactRebuildRequestWire,
)
from sase.main import artifact_handler, entry
from sase.main.parser import create_parser


def _artifact_parser() -> argparse.ArgumentParser:
    parser = create_parser()
    subparser_action = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    return subparser_action.choices["artifact"]


def _subparser_action(
    parser: argparse.ArgumentParser,
) -> argparse._SubParsersAction:
    return next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )


def test_artifact_parser_registers_required_subcommands() -> None:
    artifact_parser = _artifact_parser()

    assert set(_subparser_action(artifact_parser).choices) == {
        "add",
        "remove",
        "list",
        "show",
        "graph",
        "rebuild",
        "doctor",
    }


def test_artifact_options_all_have_short_forms() -> None:
    artifact_parser = _artifact_parser()

    for name, parser in _subparser_action(artifact_parser).choices.items():
        for action in parser._actions:
            if not action.option_strings:
                continue
            if action.dest == "help":
                continue
            assert any(
                option.startswith("-") and not option.startswith("--")
                for option in action.option_strings
            ), f"sase artifact {name} {action.dest}"


def test_entry_dispatches_artifact_command(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    def fake_handle(args: argparse.Namespace) -> None:
        seen["command"] = args.command
        raise SystemExit(0)

    monkeypatch.setattr(sys, "argv", ["sase", "artifact", "list", "-j"])
    monkeypatch.setattr(artifact_handler, "handle_artifact_command", fake_handle)

    with pytest.raises(SystemExit) as exc_info:
        entry.main()

    assert exc_info.value.code == 0
    assert seen == {"command": "artifact"}


def test_missing_artifact_subcommand_exits_nonzero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = create_parser().parse_args(["artifact"])

    with pytest.raises(SystemExit) as exc_info:
        artifact_handler.handle_artifact_command(args)

    assert exc_info.value.code == 1
    assert "Usage: sase artifact" in capsys.readouterr().out


def test_list_json_calls_facade_with_query(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    node = ArtifactNodeWire(id="file:/tmp/a.py", kind="file", display_title="a.py")
    mock_list = Mock(return_value=[node])
    monkeypatch.setattr(artifact_handler.artifact_facade, "artifact_list", mock_list)

    args = create_parser().parse_args(
        [
            "artifact",
            "list",
            "-j",
            "-i",
            str(tmp_path / "graph.sqlite"),
            "-k",
            "file",
            "-L",
            "parent",
            "-P",
            "derived",
            "-s",
            "directory",
            "-S",
            "/tmp",
            "-q",
            "needle",
            "-r",
            "/",
            "-u",
            "-l",
            "25",
            "-o",
            "5",
        ]
    )

    with pytest.raises(SystemExit) as exc_info:
        artifact_handler.handle_artifact_command(args)

    assert exc_info.value.code == 0
    mock_list.assert_called_once_with(
        tmp_path / "graph.sqlite",
        ArtifactQueryWire(
            text="needle",
            kinds=("file",),
            link_types=("parent",),
            provenance="derived",
            source_kinds=("directory",),
            source_ids=("/tmp",),
            root_id="/",
            include_tombstoned=True,
            limit=25,
            offset=5,
        ),
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["id"] == "file:/tmp/a.py"


def test_show_json_calls_facade(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    detail = {
        "schema_version": ARTIFACT_WIRE_SCHEMA_VERSION,
        "node": None,
        "payloads": [],
        "outbound_links": [],
        "inbound_links": [],
        "children": [],
        "path_to_root": [],
        "diagnostics": [],
    }
    mock_show = Mock(return_value=detail)
    monkeypatch.setattr(artifact_handler.artifact_facade, "artifact_show", mock_show)
    args = create_parser().parse_args(
        ["artifact", "show", "-j", "-i", str(tmp_path / "graph.sqlite"), "-a", "x"]
    )

    with pytest.raises(SystemExit) as exc_info:
        artifact_handler.handle_artifact_command(args)

    assert exc_info.value.code == 0
    mock_show.assert_called_once_with(tmp_path / "graph.sqlite", "x")
    assert json.loads(capsys.readouterr().out)["schema_version"] == 1


def test_graph_json_calls_facade_with_options(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    graph = {
        "schema_version": ARTIFACT_WIRE_SCHEMA_VERSION,
        "root_id": ARTIFACT_ROOT_ID,
        "nodes": [],
        "links": [],
        "node_count": 0,
        "link_count": 0,
        "truncated": False,
        "limit": 10,
    }
    mock_graph = Mock(return_value=graph)
    monkeypatch.setattr(artifact_handler.artifact_facade, "artifact_graph", mock_graph)
    args = create_parser().parse_args(
        [
            "artifact",
            "graph",
            "-j",
            "-i",
            str(tmp_path / "graph.sqlite"),
            "-a",
            "root",
            "-d",
            "4",
            "-L",
            "related",
            "-I",
            "-F",
            "-l",
            "10",
        ]
    )

    with pytest.raises(SystemExit) as exc_info:
        artifact_handler.handle_artifact_command(args)

    assert exc_info.value.code == 0
    mock_graph.assert_called_once_with(
        tmp_path / "graph.sqlite",
        ArtifactGraphOptionsWire(
            root_id="root",
            max_depth=4,
            link_types=("related",),
            include_inbound=True,
            include_outbound=True,
            full_graph=True,
            limit=10,
        ),
    )
    assert json.loads(capsys.readouterr().out)["limit"] == 10


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


def test_mutation_commands_return_clear_unimplemented_errors(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = create_parser().parse_args(["artifact", "add"])

    with pytest.raises(SystemExit) as exc_info:
        artifact_handler.handle_artifact_command(args)

    assert exc_info.value.code == 1
    assert "not implemented yet" in capsys.readouterr().err


def test_non_json_read_only_command_reports_json_requirement(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = create_parser().parse_args(["artifact", "list"])

    with pytest.raises(SystemExit) as exc_info:
        artifact_handler.handle_artifact_command(args)

    assert exc_info.value.code == 1
    assert "use `sase artifact list -j`" in capsys.readouterr().err
