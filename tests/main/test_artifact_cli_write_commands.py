"""Tests for write-oriented ``sase artifact`` CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock, call

import pytest

from sase.core.artifact_wire import (
    ARTIFACT_WIRE_SCHEMA_VERSION,
    ArtifactLinkRemoveWire,
    ArtifactLinkUpsertWire,
    ArtifactLinkWire,
    ArtifactMutationResultWire,
    ArtifactNodeRemoveWire,
    ArtifactNodeUpsertWire,
    ArtifactNodeWire,
    ArtifactPayloadWire,
)
from sase.main import artifact_handler
from sase.main.parser import create_parser


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
