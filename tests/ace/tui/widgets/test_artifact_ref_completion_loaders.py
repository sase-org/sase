"""Source loading and caching coverage for artifact reference completion."""

from __future__ import annotations

import os
from unittest.mock import patch

from sase.ace.tui.widgets._artifact_ref_entity_catalogs import (
    ArtifactRefAgentCandidate,
    _BEAD_CACHE,
    load_agent_candidate_catalog,
    load_bead_candidate_catalog,
)
from sase.ace.tui.widgets.artifact_ref_completion import (
    _ARTIFACT_INDEX_CACHE,
    _load_artifact_file_candidate_catalog,
    _read_cached_artifact_index,
    load_artifact_ref_completion_catalog,
)
from sase.artifact_refs import (
    ArtifactRefAgentOwner,
    ArtifactRefAgentRoot,
    ArtifactRefBeadStore,
    ArtifactRefContext,
    ArtifactRefProject,
)
from sase.bead.model import BeadTier, Issue, IssueType, Status
from sase.core.artifact_file_types import ArtifactFile


def test_chat_catalog_scan_is_bounded(tmp_path) -> None:
    yielded = 0

    def _chat_files():
        nonlocal yielded
        for index in range(4):
            yielded += 1
            path = tmp_path / f"{index}.md"
            path.touch()
            yield path

    context = ArtifactRefContext(
        document_roots=(),
        chats_root=tmp_path,
        artifact_index_path=tmp_path / "missing-index.jsonl",
        repositories=(),
        projects=(),
    )
    with (
        patch(
            "sase.history.chat_storage.iter_chat_files",
            return_value=_chat_files(),
        ),
        patch(
            "sase.ace.tui.widgets.artifact_ref_completion._MAX_CHAT_SCAN_ROWS",
            2,
        ),
        patch(
            "sase.ace.tui.widgets.artifact_ref_completion._MAX_CHAT_ROWS",
            2,
        ),
    ):
        catalog = load_artifact_ref_completion_catalog(None, context)

    assert yielded == 4
    assert len(catalog.chats) == 2
    assert catalog.payload_truncation["chat"] == 2


def test_artifact_index_cache_miss_queries_rust_and_reuses_unchanged_token(
    tmp_path,
) -> None:
    index = tmp_path / "index.jsonl"
    index.write_text("{}\n", encoding="utf-8")
    row = ArtifactFile(
        id="explicit:abc123",
        label="Diagram",
        kind="image",
        path="/stored/diagram.png",
    )
    resolved = index.resolve()
    _ARTIFACT_INDEX_CACHE.pop(resolved, None)

    with patch(
        "sase.core.artifact_file_query_facade.query_artifact_files",
        return_value=[row],
    ) as query:
        first = _read_cached_artifact_index(index)
        second = _read_cached_artifact_index(index)

    assert first == second == (row,)
    query.assert_called_once_with(resolved)


def test_artifact_file_catalog_preserves_rust_order_and_project_alias_filtering(
    tmp_path,
) -> None:
    def row(
        artifact_id: str,
        project: str | None,
    ) -> ArtifactFile:
        return ArtifactFile(
            id=artifact_id,
            label=artifact_id,
            kind="image",
            path=f"/stored/{artifact_id}.png",
            created_at="2026-07-29T12:00:00Z",
            project=project,
        )

    rust_ordered_rows = (
        row("explicit:aaa", None),
        row("explicit:bbb", "ss"),
        row("explicit:ignored", "other"),
        row("explicit:ccc", "gh_sase-org__sase"),
    )
    context = ArtifactRefContext(
        document_roots=(),
        chats_root=tmp_path,
        artifact_index_path=tmp_path / "index.jsonl",
        repositories=(),
        projects=(
            ArtifactRefProject(
                name="sase",
                key="gh_sase-org__sase",
                aliases=("ss",),
            ),
        ),
    )

    with patch(
        "sase.ace.tui.widgets.artifact_ref_completion._read_cached_artifact_index",
        return_value=rust_ordered_rows,
    ):
        candidates = _load_artifact_file_candidate_catalog("sase", context).rows

    assert [candidate.payload for candidate in candidates] == [
        "explicit:aaa",
        "explicit:bbb",
        "explicit:ccc",
    ]


def test_bead_catalog_caches_sorts_and_caps_rows(tmp_path) -> None:
    root = tmp_path / "beads"
    root.mkdir()
    (root / "issues.jsonl").write_text("{}\n", encoding="utf-8")
    _BEAD_CACHE.pop(root.resolve(), None)
    issues = [
        Issue(
            id=f"sase-{index}",
            title=f"Issue {index}",
            status=Status.IN_PROGRESS,
            issue_type=IssueType.PLAN,
            tier=BeadTier.EPIC if index == 500 else BeadTier.PLAN,
            updated_at=f"2026-07-29T12:{index // 60:02d}:{index % 60:02d}Z",
        )
        for index in range(501)
    ]
    context = ArtifactRefContext(
        document_roots=(),
        chats_root=tmp_path / "chats",
        artifact_index_path=tmp_path / "artifacts.jsonl",
        repositories=(),
        projects=(),
        bead_stores=(ArtifactRefBeadStore("sase", "sase", root),),
    )

    with patch(
        "sase.core.bead_read_facade.list_issues",
        return_value=issues,
    ) as list_rows:
        first = load_bead_candidate_catalog(context).rows
        second = load_bead_candidate_catalog(context).rows

    assert first == second
    assert len(first) == 500
    assert first[0].payload == "sase-500"
    assert first[0].detail == "in_progress · epic"
    list_rows.assert_called_once_with(root.resolve())


def test_agent_catalog_inserts_global_name_and_labels_current_owner(
    monkeypatch,
    tmp_path,
) -> None:
    agents_dir = tmp_path / "agents-root" / "agents"
    current = agents_dir / "bbugyi200.athena.9w"
    foreign = agents_dir / "alice.zeus.foo"
    current.mkdir(parents=True)
    foreign.mkdir()
    (current / "README.md").touch()
    (foreign / "README.md").touch()
    os.utime(current, (20, 20))
    os.utime(foreign, (10, 10))
    context = ArtifactRefContext(
        document_roots=(),
        chats_root=tmp_path / "chats",
        artifact_index_path=tmp_path / "artifacts.jsonl",
        repositories=(),
        projects=(),
        agent_roots=(ArtifactRefAgentRoot("sase", tmp_path / "agents-root"),),
        agent_owner=ArtifactRefAgentOwner("bbugyi200", "athena"),
    )
    rows = load_agent_candidate_catalog(context).rows

    assert rows == (
        ArtifactRefAgentCandidate(
            payload="bbugyi200.athena.9w",
            label="9w",
            detail="sase",
            updated_at=20,
        ),
        ArtifactRefAgentCandidate(
            payload="alice.zeus.foo",
            label="alice.zeus.foo",
            detail="alice.zeus",
            updated_at=10,
        ),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets._artifact_ref_entity_catalogs._MAX_ENTITY_ROWS",
        1,
    )
    assert load_agent_candidate_catalog(context).rows == rows[:1]
