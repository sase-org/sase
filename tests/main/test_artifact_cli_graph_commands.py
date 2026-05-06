"""Tests for graph-oriented ``sase artifact`` CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from sase.core.artifact_wire import (
    ARTIFACT_ROOT_ID,
    ARTIFACT_WIRE_SCHEMA_VERSION,
    ArtifactGraphOptionsWire,
    ArtifactGraphWire,
    ArtifactLinkWire,
    ArtifactNodeWire,
)
from sase.main import artifact_handler
from sase.main.parser import create_parser


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
