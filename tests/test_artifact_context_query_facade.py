"""Tests for the Rust-backed batched artifact-context query facade."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.core.artifact_context_query_facade import (
    ArtifactContextProducerGroup,
    query_artifact_context,
)


def _write_index(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps({"schema_version": 2, "artifact": row}) for row in rows)
        + "\n",
        encoding="utf-8",
    )


def _row(
    artifact_id: str,
    *,
    agent_artifacts_dir: str,
    kind: str = "markdown",
    created_at: str = "2026-07-01T00:00:00Z",
    agent_name: str = "researcher.a",
    explicit: bool = False,
) -> dict[str, Any]:
    return {
        "id": artifact_id,
        "label": f"Label {artifact_id}",
        "kind": kind,
        "path": f"/stored/{artifact_id}.md",
        "source_path": f"/source/{artifact_id}.md",
        "created_at": created_at,
        "agent_artifacts_dir": agent_artifacts_dir,
        "agent_name": agent_name,
        "explicit": explicit,
    }


def test_query_checks_handshake_and_batches_groups_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []

    def fake_require(name: str) -> Any:
        if name == "artifact_context_query_wire_schema_version":
            return lambda: 1
        if name == "artifact_context_query":

            def query(path: str, groups: list[dict[str, object]]) -> list[object]:
                calls.append((path, groups))
                return []

            return query
        raise AssertionError(name)

    monkeypatch.setattr(
        "sase.core.artifact_context_query_facade.require_rust_binding",
        fake_require,
    )

    result = query_artifact_context(
        [
            ArtifactContextProducerGroup("research.a", ["/producers/a"]),
            ArtifactContextProducerGroup(
                "research.b", ["/producers/b1", "/producers/b2"]
            ),
        ],
        index_path="/tmp/index.jsonl",
    )

    assert result == []
    assert calls == [
        (
            str(Path("/tmp/index.jsonl").resolve(strict=False)),
            [
                {
                    "wait_name": "research.a",
                    "agent_artifacts_dirs": ["/producers/a"],
                },
                {
                    "wait_name": "research.b",
                    "agent_artifacts_dirs": ["/producers/b1", "/producers/b2"],
                },
            ],
        )
    ]


def test_query_rejects_stale_handshake(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.core.artifact_context_query_facade.require_rust_binding",
        lambda _name: lambda: 2,
    )

    with pytest.raises(RuntimeError, match="expected 1, got 2"):
        query_artifact_context([], index_path="/tmp/index.jsonl")


@pytest.mark.parametrize(
    ("row", "match"),
    [
        ({"wait_name": "a"}, "ref must be a non-empty string"),
        ({"ref": "file:1"}, "wait_name must be a non-empty string"),
        (
            {"wait_name": "a", "ref": "file:1", "explicit": "yes"},
            "explicit must be a boolean",
        ),
        (
            {"wait_name": "a", "ref": "file:1", "explicit": False, "path": None},
            "path or complete VCS provenance",
        ),
        (
            {
                "wait_name": "a",
                "ref": "file:1",
                "explicit": False,
                "path": "/stored/1.md",
                "kind": 3,
            },
            "kind must be a string or null",
        ),
        ("not-an-object", "expected an object"),
    ],
)
def test_query_rejects_incompatible_rows(
    row: object,
    match: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_require(name: str) -> Any:
        if name == "artifact_context_query_wire_schema_version":
            return lambda: 1
        return lambda *_args: [row]

    monkeypatch.setattr(
        "sase.core.artifact_context_query_facade.require_rust_binding",
        fake_require,
    )

    with pytest.raises(RuntimeError, match=match):
        query_artifact_context(
            [ArtifactContextProducerGroup("a", ["/producers/a"])],
            index_path="/tmp/index.jsonl",
        )


def test_query_accepts_vcs_backed_row_without_stored_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = {
        "wait_name": "a",
        "ref": "file:vcs",
        "explicit": True,
        "path": None,
        "vcs_repo": "sase--research",
        "vcs_sha": "b" * 40,
        "vcs_relpath": "202609/topic__a.md",
    }

    def fake_require(name: str) -> Any:
        if name == "artifact_context_query_wire_schema_version":
            return lambda: 1
        return lambda *_args: [row]

    monkeypatch.setattr(
        "sase.core.artifact_context_query_facade.require_rust_binding",
        fake_require,
    )

    [entry] = query_artifact_context(
        [ArtifactContextProducerGroup("a", ["/producers/a"])],
        index_path="/tmp/index.jsonl",
    )
    assert entry["path"] is None
    assert entry["vcs_repo"] == "sase--research"


def test_real_rust_query_matches_exact_producer_and_excludes_chats(
    tmp_path: Path,
) -> None:
    index = tmp_path / "index.jsonl"
    _write_index(
        index,
        [
            _row("report", agent_artifacts_dir="/producers/a"),
            _row("transcript", agent_artifacts_dir="/producers/a", kind="chat"),
            _row("other-producer", agent_artifacts_dir="/producers/other"),
        ],
    )

    entries = query_artifact_context(
        [ArtifactContextProducerGroup("research.a", ["/producers/a"])],
        index_path=index,
    )

    assert [entry["ref"] for entry in entries] == ["file:report"]
    assert entries[0]["wait_name"] == "research.a"
    assert entries[0]["agent_name"] == "researcher.a"


def test_real_rust_query_orders_by_dependency_and_deduplicates_overlaps(
    tmp_path: Path,
) -> None:
    index = tmp_path / "index.jsonl"
    _write_index(
        index,
        [
            _row(
                "b-report",
                agent_artifacts_dir="/producers/b",
                created_at="2026-07-01T00:00:00Z",
            ),
            _row(
                "a-report",
                agent_artifacts_dir="/producers/a",
                created_at="2026-07-02T00:00:00Z",
            ),
        ],
    )

    entries = query_artifact_context(
        [
            ArtifactContextProducerGroup("research.a", ["/producers/a"]),
            ArtifactContextProducerGroup("research.b", ["/producers/b"]),
        ],
        index_path=index,
    )

    assert [entry["ref"] for entry in entries] == ["file:a-report", "file:b-report"]


def test_real_rust_query_empty_batch_never_touches_the_index(
    tmp_path: Path,
) -> None:
    # A directory in place of the index file: an attempt to read it as a
    # file would surface an error, so a clean [] here proves the empty
    # batch never opened it.
    index = tmp_path / "index.jsonl"
    index.mkdir()

    assert query_artifact_context([], index_path=index) == []
    assert (
        query_artifact_context(
            [ArtifactContextProducerGroup("a", [])], index_path=index
        )
        == []
    )
