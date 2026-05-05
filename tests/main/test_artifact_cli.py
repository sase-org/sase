"""Tests for the ``sase artifact`` CLI parser and JSON handlers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import Mock, call

import pytest

from sase.core.artifact_wire import (
    ARTIFACT_ROOT_ID,
    ARTIFACT_WIRE_SCHEMA_VERSION,
    ArtifactDetailWire,
    ArtifactDoctorIssueWire,
    ArtifactDoctorOptionsWire,
    ArtifactDoctorWire,
    ArtifactGraphOptionsWire,
    ArtifactGraphWire,
    ArtifactLinkRemoveWire,
    ArtifactLinkUpsertWire,
    ArtifactLinkWire,
    ArtifactMutationResultWire,
    ArtifactNodeRemoveWire,
    ArtifactNodeUpsertWire,
    ArtifactNodeWire,
    ArtifactPayloadWire,
    ArtifactQueryWire,
    ArtifactRebuildRequestWire,
)
from sase.core.rust import RUST_EXTENSION_MODULE_NAME
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


def test_artifact_docs_cover_registered_subcommands() -> None:
    docs_path = Path(__file__).parents[2] / "docs" / "artifacts.md"
    docs = docs_path.read_text()
    subcommands = _subparser_action(_artifact_parser()).choices

    for subcommand in subcommands:
        assert f"sase artifact {subcommand}" in docs


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


def test_list_human_outputs_compact_table(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    node = ArtifactNodeWire(
        id="file:/tmp/a.py",
        kind="file",
        display_title="a.py",
        provenance="derived",
        source_kind="directory",
        source_id="/tmp",
        updated_at="2026-05-05T12:00:00Z",
    )
    monkeypatch.setattr(
        artifact_handler.artifact_facade,
        "artifact_list",
        Mock(return_value=[node]),
    )
    args = create_parser().parse_args(
        ["artifact", "list", "-i", str(tmp_path / "graph.sqlite")]
    )

    with pytest.raises(SystemExit) as exc_info:
        artifact_handler.handle_artifact_command(args)

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "KIND" in output
    assert "file:/tmp/a.py" in output
    assert "directory:/tmp" in output


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


def test_show_human_outputs_detail_sections(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    node = ArtifactNodeWire(
        id="note:1",
        kind="note",
        display_title="Design note",
        provenance="manual",
        updated_at="2026-05-05T12:00:00Z",
    )
    detail = ArtifactDetailWire(
        schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
        node=node,
        payloads=[
            ArtifactPayloadWire(
                artifact_id="note:1",
                payload_type="summary",
                payload={"body": "hello"},
            )
        ],
        outbound_links=[
            ArtifactLinkWire(
                id="link-1",
                link_type="related",
                source_id="note:1",
                target_id="note:2",
            )
        ],
        inbound_links=[],
        children=[ArtifactNodeWire(id="note:1.1", kind="note", display_title="Child")],
        path_to_root=[
            ArtifactNodeWire(id="/", kind="root", display_title="/"),
            node,
        ],
        diagnostics=[
            ArtifactDoctorIssueWire(
                issue_type="dangling_link",
                severity="warning",
                artifact_id="note:1",
                message="example diagnostic",
            )
        ],
    )
    monkeypatch.setattr(
        artifact_handler.artifact_facade,
        "artifact_show",
        Mock(return_value=detail),
    )
    args = create_parser().parse_args(
        ["artifact", "show", "-i", str(tmp_path / "graph.sqlite"), "-a", "note:1"]
    )

    with pytest.raises(SystemExit) as exc_info:
        artifact_handler.handle_artifact_command(args)

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "Artifact: Design note" in output
    assert "Path to root:" in output
    assert "/ -> note:1" in output
    assert "Children:" in output
    assert "related:" in output
    assert "object keys: body" in output
    assert "example diagnostic" in output


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


def test_graph_text_outputs_compact_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    graph = ArtifactGraphWire(
        schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
        root_id="root",
        nodes=[
            ArtifactNodeWire(id="root", kind="root", display_title="root"),
            ArtifactNodeWire(id="child", kind="file", display_title="child"),
        ],
        links=[
            ArtifactLinkWire(
                id="link-1",
                link_type="parent",
                source_id="child",
                target_id="root",
            )
        ],
        node_count=3,
        link_count=1,
        truncated=True,
        limit=2,
    )
    mock_graph = Mock(return_value=graph)
    monkeypatch.setattr(artifact_handler.artifact_facade, "artifact_graph", mock_graph)
    args = create_parser().parse_args(
        [
            "artifact",
            "graph",
            "-f",
            "text",
            "-i",
            str(tmp_path / "graph.sqlite"),
            "-a",
            "root",
            "-l",
            "2",
        ]
    )

    with pytest.raises(SystemExit) as exc_info:
        artifact_handler.handle_artifact_command(args)

    assert exc_info.value.code == 0
    mock_graph.assert_called_once_with(
        tmp_path / "graph.sqlite",
        ArtifactGraphOptionsWire(root_id="root", limit=2),
    )
    output = capsys.readouterr().out
    assert "nodes: 2 shown / 3 total" in output
    assert "truncated: true" in output
    assert "child -[parent]-> root" in output


@pytest.mark.parametrize("output_format", ["dot", "mermaid"])
def test_graph_export_formats_print_raw_rust_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    output_format: str,
) -> None:
    mock_export = Mock(return_value=f"{output_format} output\n")
    monkeypatch.setattr(
        artifact_handler.artifact_facade,
        "artifact_export",
        mock_export,
    )
    args = create_parser().parse_args(
        [
            "artifact",
            "graph",
            "-f",
            output_format,
            "-i",
            str(tmp_path / "graph.sqlite"),
            "-a",
            "root",
            "-L",
            "parent",
            "-I",
            "-l",
            "10",
        ]
    )

    with pytest.raises(SystemExit) as exc_info:
        artifact_handler.handle_artifact_command(args)

    assert exc_info.value.code == 0
    mock_export.assert_called_once_with(
        tmp_path / "graph.sqlite",
        ArtifactGraphOptionsWire(
            root_id="root",
            link_types=("parent",),
            include_inbound=True,
            limit=10,
        ),
        output_format,
    )
    assert capsys.readouterr().out == f"{output_format} output\n"


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


def test_add_json_builds_node_upsert_request(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    result = ArtifactMutationResultWire(
        schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
        operation="upsert_node",
        nodes_added=1,
        affected_node_ids=["note:1"],
    )
    mock_add = Mock(return_value=result)
    monkeypatch.setattr(artifact_handler.artifact_facade, "artifact_add", mock_add)
    args = create_parser().parse_args(
        [
            "artifact",
            "add",
            "-j",
            "-i",
            str(tmp_path / "graph.sqlite"),
            "-a",
            "note:1",
            "-k",
            "note",
            "-t",
            "Design note",
            "-s",
            "subtitle",
            "-q",
            "search text",
            "-m",
            '{"priority": 2}',
        ]
    )

    with pytest.raises(SystemExit) as exc_info:
        artifact_handler.handle_artifact_command(args)

    assert exc_info.value.code == 0
    mock_add.assert_called_once_with(
        tmp_path / "graph.sqlite",
        ArtifactNodeUpsertWire(
            schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
            node=ArtifactNodeWire(
                id="note:1",
                kind="note",
                display_title="Design note",
                subtitle="subtitle",
                search_text="search text",
                metadata={"priority": 2},
            ),
        ),
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["operation"] == "add"
    assert payload["nodes_added"] == 1
    assert payload["affected_node_ids"] == ["note:1"]


def test_add_json_can_upsert_payload_and_links(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    mock_add = Mock(
        side_effect=[
            ArtifactMutationResultWire(
                schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
                operation="upsert_node",
                nodes_added=1,
                affected_node_ids=["note:1"],
            ),
            ArtifactMutationResultWire(
                schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
                operation="upsert_payload",
                nodes_updated=1,
                affected_node_ids=["note:1"],
            ),
            ArtifactMutationResultWire(
                schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
                operation="upsert_link",
                links_added=1,
                affected_link_ids=["link-1"],
            ),
            ArtifactMutationResultWire(
                schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
                operation="upsert_link",
                links_added=1,
                affected_link_ids=["link-2"],
            ),
        ]
    )
    monkeypatch.setattr(artifact_handler.artifact_facade, "artifact_add", mock_add)
    args = create_parser().parse_args(
        [
            "artifact",
            "add",
            "-j",
            "-i",
            str(tmp_path / "graph.sqlite"),
            "-a",
            "note:1",
            "-k",
            "note",
            "-P",
            "summary",
            "-p",
            '{"body": "hello"}',
            "-l",
            "parent|note:1|/",
            "-L",
            '{"id": "link-json", "link_type": "related", "source_id": "note:1", "target_id": "note:2", "metadata": {"rank": 1}}',
        ]
    )

    with pytest.raises(SystemExit) as exc_info:
        artifact_handler.handle_artifact_command(args)

    assert exc_info.value.code == 0
    mock_add.assert_has_calls(
        [
            call(
                tmp_path / "graph.sqlite",
                ArtifactNodeUpsertWire(
                    schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
                    node=ArtifactNodeWire(
                        id="note:1",
                        kind="note",
                        display_title="note:1",
                    ),
                ),
            ),
            call(
                tmp_path / "graph.sqlite",
                ArtifactPayloadWire(
                    artifact_id="note:1",
                    payload_type="summary",
                    payload={"body": "hello"},
                ),
            ),
            call(
                tmp_path / "graph.sqlite",
                ArtifactLinkUpsertWire(
                    schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
                    link=ArtifactLinkWire(
                        id="",
                        link_type="parent",
                        source_id="note:1",
                        target_id="/",
                    ),
                ),
            ),
            call(
                tmp_path / "graph.sqlite",
                ArtifactLinkUpsertWire(
                    schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
                    link=ArtifactLinkWire(
                        id="link-json",
                        link_type="related",
                        source_id="note:1",
                        target_id="note:2",
                        metadata={"rank": 1},
                    ),
                ),
            ),
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["nodes_added"] == 1
    assert payload["nodes_updated"] == 1
    assert payload["links_added"] == 2
    assert payload["affected_node_ids"] == ["note:1"]
    assert payload["affected_link_ids"] == ["link-1", "link-2"]


def test_remove_json_builds_node_remove_request(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    result = ArtifactMutationResultWire(
        schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
        operation="remove_node",
        nodes_removed=1,
        affected_node_ids=["note:1"],
    )
    mock_remove = Mock(return_value=result)
    monkeypatch.setattr(
        artifact_handler.artifact_facade, "artifact_remove", mock_remove
    )
    args = create_parser().parse_args(
        [
            "artifact",
            "remove",
            "-j",
            "-i",
            str(tmp_path / "graph.sqlite"),
            "-a",
            "note:1",
            "-p",
            "manual",
            "-r",
            "obsolete",
        ]
    )

    with pytest.raises(SystemExit) as exc_info:
        artifact_handler.handle_artifact_command(args)

    assert exc_info.value.code == 0
    mock_remove.assert_called_once_with(
        tmp_path / "graph.sqlite",
        ArtifactNodeRemoveWire(
            schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
            id="note:1",
            provenance="manual",
            reason="obsolete",
        ),
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["operation"] == "remove"
    assert payload["nodes_removed"] == 1
    assert payload["affected_node_ids"] == ["note:1"]


def test_remove_json_builds_link_remove_request(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    result = ArtifactMutationResultWire(
        schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
        operation="remove_link",
        tombstones_added=1,
        affected_link_ids=["link-1"],
        tombstone_ids=["7"],
    )
    mock_remove = Mock(return_value=result)
    monkeypatch.setattr(
        artifact_handler.artifact_facade, "artifact_remove", mock_remove
    )
    args = create_parser().parse_args(
        [
            "artifact",
            "remove",
            "-j",
            "-i",
            str(tmp_path / "graph.sqlite"),
            "-T",
            "related",
            "-S",
            "note:1",
            "-D",
            "note:2",
            "-p",
            "derived",
            "-r",
            "wrong edge",
        ]
    )

    with pytest.raises(SystemExit) as exc_info:
        artifact_handler.handle_artifact_command(args)

    assert exc_info.value.code == 0
    mock_remove.assert_called_once_with(
        tmp_path / "graph.sqlite",
        ArtifactLinkRemoveWire(
            schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
            link_type="related",
            source_id="note:1",
            target_id="note:2",
            provenance="derived",
            reason="wrong edge",
        ),
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["affected_link_ids"] == ["link-1"]
    assert payload["tombstone_ids"] == ["7"]


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


def _run_entry(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *argv: str,
) -> tuple[int, str, str]:
    monkeypatch.setattr(sys, "argv", ["sase", *argv])
    with pytest.raises(SystemExit) as exc_info:
        entry.main()
    captured = capsys.readouterr()
    code = exc_info.value.code
    return int(code) if isinstance(code, int) else 0, captured.out, captured.err


def test_artifact_cli_real_extension_temp_index_e2e(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    required = {
        "artifact_add",
        "artifact_remove",
        "artifact_list",
        "artifact_show",
        "artifact_graph",
        "artifact_doctor",
    }
    missing = sorted(name for name in required if not hasattr(rust_module, name))
    if missing:
        pytest.skip(f"sase_core_rs is too old: missing {missing}")

    index_path = tmp_path / "artifacts.sqlite"

    code, output, error = _run_entry(
        monkeypatch,
        capsys,
        "artifact",
        "add",
        "-j",
        "-i",
        str(index_path),
        "-a",
        "doc:parent",
        "-k",
        "note",
        "-t",
        "Parent note",
        "-q",
        "parent note",
        "-l",
        "parent|doc:parent|/",
    )
    assert (code, error) == (0, "")
    assert json.loads(output)["affected_node_ids"] == ["doc:parent"]

    code, output, error = _run_entry(
        monkeypatch,
        capsys,
        "artifact",
        "add",
        "-j",
        "-i",
        str(index_path),
        "-a",
        "doc:child",
        "-k",
        "note",
        "-t",
        "Child note",
        "-q",
        "child note",
        "-P",
        "summary",
        "-p",
        '{"body": "child payload"}',
        "-l",
        "parent|doc:child|doc:parent",
    )
    add_payload = json.loads(output)
    assert (code, error) == (0, "")
    assert add_payload["affected_node_ids"] == ["doc:child"]
    assert add_payload["nodes_added"] == 1
    assert add_payload["links_added"] == 1

    code, output, error = _run_entry(
        monkeypatch,
        capsys,
        "artifact",
        "list",
        "-j",
        "-i",
        str(index_path),
        "-q",
        "child",
        "-l",
        "10",
    )
    listed = json.loads(output)
    assert (code, error) == (0, "")
    assert [node["id"] for node in listed] == ["doc:child"]

    code, output, error = _run_entry(
        monkeypatch,
        capsys,
        "artifact",
        "show",
        "-j",
        "-i",
        str(index_path),
        "-a",
        "doc:child",
    )
    detail = json.loads(output)
    assert (code, error) == (0, "")
    assert detail["node"]["display_title"] == "Child note"
    assert detail["payloads"][0]["payload"] == {"body": "child payload"}
    assert [node["id"] for node in detail["path_to_root"]] == [
        "doc:child",
        "doc:parent",
        "/",
    ]

    code, output, error = _run_entry(
        monkeypatch,
        capsys,
        "artifact",
        "graph",
        "-f",
        "text",
        "-i",
        str(index_path),
        "-a",
        "doc:parent",
        "-d",
        "2",
        "-I",
        "-l",
        "20",
    )
    assert (code, error) == (0, "")
    assert "doc:child -[parent]-> doc:parent" in output
    assert "truncated: false" in output

    code, output, error = _run_entry(
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

    code, output, error = _run_entry(
        monkeypatch,
        capsys,
        "artifact",
        "remove",
        "-j",
        "-i",
        str(index_path),
        "-T",
        "parent",
        "-S",
        "doc:child",
        "-D",
        "doc:parent",
        "-p",
        "manual",
        "-r",
        "integration test cleanup",
    )
    removed_link = json.loads(output)
    assert (code, error) == (0, "")
    assert removed_link["links_removed"] + removed_link["tombstones_added"] >= 1

    code, output, error = _run_entry(
        monkeypatch,
        capsys,
        "artifact",
        "remove",
        "-j",
        "-i",
        str(index_path),
        "-a",
        "doc:child",
        "-p",
        "manual",
        "-r",
        "integration test cleanup",
    )
    removed_node = json.loads(output)
    assert (code, error) == (0, "")
    assert removed_node["affected_node_ids"] == ["doc:child"]


def test_artifact_cli_real_extension_migration_fixture_smoke(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    required = {
        "artifact_rebuild",
        "artifact_list",
        "artifact_show",
        "artifact_graph",
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
    artifact_dir = project_dir / "artifacts" / "ace-run" / "20260505120000"
    response_path = artifact_dir / "response.md"

    project_dir.mkdir(parents=True)
    beads_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    project_file.write_text(
        "NAME: cl-one\n"
        "DESCRIPTION: Build the artifact graph migration.\n"
        "STATUS: WIP\n"
        "COMMITS:\n"
        "  (1) Initial note\n",
        encoding="utf-8",
    )
    response_path.write_text("migration response\n", encoding="utf-8")
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "agent-alpha",
                "artifact_agent_id": "agent-alpha",
                "changespec_name": "cl-one",
                "llm_provider": "codex",
                "phase_bead_id": "sase-10.1",
            }
        ),
        encoding="utf-8",
    )
    (artifact_dir / "done.json").write_text(
        json.dumps(
            {
                "name": "agent-alpha",
                "cl_name": "cl-one",
                "response_path": str(response_path),
            }
        ),
        encoding="utf-8",
    )
    (artifact_dir / "codex_thinking.jsonl").write_text(
        json.dumps(
            {
                "text": "verify migrated graph relationships",
                "timestamp": "2026-05-05T12:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (beads_dir / "issues.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "sase-10",
                        "title": "Epic",
                        "status": "open",
                        "issue_type": "plan",
                        "tier": "epic",
                        "owner": "owner@example.com",
                        "assignee": "",
                        "created_at": "2026-05-05T00:00:00Z",
                        "created_by": "owner@example.com",
                        "updated_at": "2026-05-05T00:00:00Z",
                        "description": "",
                        "notes": "",
                        "design": "",
                        "is_ready_to_work": True,
                        "changespec_name": "cl-one",
                        "dependencies": [],
                    }
                ),
                json.dumps(
                    {
                        "id": "sase-10.1",
                        "title": "Phase",
                        "status": "in_progress",
                        "issue_type": "phase",
                        "parent_id": "sase-10",
                        "owner": "owner@example.com",
                        "assignee": "agent-alpha",
                        "created_at": "2026-05-05T00:00:00Z",
                        "created_by": "owner@example.com",
                        "updated_at": "2026-05-05T00:00:00Z",
                        "description": "",
                        "notes": "",
                        "design": "",
                        "is_ready_to_work": False,
                        "dependencies": [],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    code, output, error = _run_entry(
        monkeypatch,
        capsys,
        "artifact",
        "rebuild",
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
    rebuild = json.loads(output)
    assert (code, error) == (0, "")
    assert rebuild["errors"] == []
    assert rebuild["nodes_added"] > 0
    assert rebuild["links_added"] > 0

    code, output, error = _run_entry(
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

    code, output, error = _run_entry(
        monkeypatch,
        capsys,
        "artifact",
        "list",
        "-j",
        "-i",
        str(index_path),
        "-k",
        "thought",
        "-l",
        "5",
    )
    thoughts = json.loads(output)
    assert (code, error) == (0, "")
    assert len(thoughts) == 1
    assert thoughts[0]["id"].startswith("thought:")

    code, output, error = _run_entry(
        monkeypatch,
        capsys,
        "artifact",
        "show",
        "-j",
        "-i",
        str(index_path),
        "-a",
        "agent-alpha",
    )
    agent = json.loads(output)
    assert (code, error) == (0, "")
    assert agent["node"]["kind"] == "agent"
    assert agent["node"]["metadata"]["source_artifact_dir"] == str(artifact_dir)
    assert any(
        link["link_type"] == "related"
        and link["source_id"] == "agent-alpha"
        and link["target_id"] == "cl-one"
        for link in agent["outbound_links"]
    )
    assert any(
        link["link_type"] == "created" and link["target_id"] == str(response_path)
        for link in agent["outbound_links"]
    )
    assert any(
        link["link_type"] == "created" and link["target_id"].startswith("thought:")
        for link in agent["outbound_links"]
    )

    code, output, error = _run_entry(
        monkeypatch,
        capsys,
        "artifact",
        "show",
        "-j",
        "-i",
        str(index_path),
        "-a",
        "sase-10.1",
    )
    phase = json.loads(output)
    assert (code, error) == (0, "")
    assert any(
        link["link_type"] == "worker"
        and link["source_id"] == "sase-10.1"
        and link["target_id"] == "agent-alpha"
        for link in phase["outbound_links"]
    )

    code, output, error = _run_entry(
        monkeypatch,
        capsys,
        "artifact",
        "graph",
        "-j",
        "-i",
        str(index_path),
        "-a",
        "cl-one",
        "-d",
        "1",
        "-I",
        "-l",
        "50",
    )
    graph = json.loads(output)
    graph_ids = {node["id"] for node in graph["nodes"]}
    assert (code, error) == (0, "")
    assert {"cl-one", "cl-one:1", "agent-alpha", "sase-10"} <= graph_ids
