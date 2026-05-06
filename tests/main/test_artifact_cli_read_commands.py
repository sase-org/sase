"""Tests for read-oriented ``sase artifact`` CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from sase.core.artifact_wire import (
    ARTIFACT_ROOT_ID,
    ARTIFACT_WIRE_SCHEMA_VERSION,
    ArtifactDetailWire,
    ArtifactDoctorIssueWire,
    ArtifactGraphOptionsWire,
    ArtifactGraphWire,
    ArtifactLinkWire,
    ArtifactNodeWire,
    ArtifactPayloadWire,
    ArtifactQueryWire,
)
from sase.main import artifact_handler
from sase.main.parser import create_parser


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
            "-F",
            "plan",
            "-F",
            "diff",
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
            file_types=("plan", "diff"),
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


def test_search_json_calls_facade_search_with_query(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    node = ArtifactNodeWire(id="file:/tmp/a.py", kind="file", display_title="a.py")
    mock_search = Mock(return_value=[node])
    monkeypatch.setattr(
        artifact_handler.artifact_facade, "artifact_search", mock_search
    )

    args = create_parser().parse_args(
        [
            "artifact",
            "search",
            "-j",
            "-i",
            str(tmp_path / "graph.sqlite"),
            "-k",
            "file",
            "-F",
            "plan",
            "-q",
            "needle",
            "-l",
            "25",
            "-o",
            "5",
        ]
    )

    with pytest.raises(SystemExit) as exc_info:
        artifact_handler.handle_artifact_command(args)

    assert exc_info.value.code == 0
    mock_search.assert_called_once_with(
        tmp_path / "graph.sqlite",
        ArtifactQueryWire(
            text="needle",
            kinds=("file",),
            file_types=("plan",),
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
        metadata={"artifact_type": "plan"},
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
    assert "FILE TYPE" in output
    assert "plan" in output
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


def test_show_human_outputs_file_type_with_misc_compatibility(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    detail = ArtifactDetailWire(
        schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
        node=ArtifactNodeWire(
            id="file:/tmp/unknown",
            kind="file",
            display_title="unknown",
            metadata={"artifact_type": "surprise"},
        ),
    )
    monkeypatch.setattr(
        artifact_handler.artifact_facade,
        "artifact_show",
        Mock(return_value=detail),
    )
    args = create_parser().parse_args(
        [
            "artifact",
            "show",
            "-i",
            str(tmp_path / "graph.sqlite"),
            "-a",
            "file:/tmp/unknown",
        ]
    )

    with pytest.raises(SystemExit) as exc_info:
        artifact_handler.handle_artifact_command(args)

    assert exc_info.value.code == 0
    assert "file type: misc" in capsys.readouterr().out


def test_show_human_truncates_long_payload_scalars(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    long_payload = "x" * 120
    detail = ArtifactDetailWire(
        schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
        node=ArtifactNodeWire(id="note:1", kind="note", display_title="Design note"),
        payloads=[
            ArtifactPayloadWire(
                artifact_id="note:1",
                payload_type="summary",
                payload=long_payload,
            )
        ],
        outbound_links=[],
        inbound_links=[],
        children=[],
        path_to_root=[],
        diagnostics=[],
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
    assert (
        '"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx...'
        in output
    )
    assert long_payload not in output


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
