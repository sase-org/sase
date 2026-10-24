"""Source loading and caching coverage for artifact reference completion."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import os
from threading import Event, Lock
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


def test_artifact_index_cache_bounds_sources_and_reloads_evicted_path(
    tmp_path,
) -> None:
    _ARTIFACT_INDEX_CACHE.clear()
    indexes = []
    rows = {}
    for index in range(9):
        path = tmp_path / f"index-{index}.jsonl"
        path.write_text("{}\n", encoding="utf-8")
        indexes.append(path)
        rows[path.resolve()] = ArtifactFile(
            id=f"explicit:{index:03d}",
            label=f"row-{index}",
            kind="image",
            path=f"/stored/{index}.png",
        )

    with patch(
        "sase.core.artifact_file_query_facade.query_artifact_files",
        side_effect=lambda path: [rows[path]],
    ) as query:
        first = _read_cached_artifact_index(indexes[0])
        for path in indexes[1:8]:
            _read_cached_artifact_index(path)
        assert _read_cached_artifact_index(indexes[0]) == first
        _read_cached_artifact_index(indexes[8])

        assert len(_ARTIFACT_INDEX_CACHE) == 8
        assert indexes[0].resolve() in _ARTIFACT_INDEX_CACHE
        assert indexes[1].resolve() not in _ARTIFACT_INDEX_CACHE
        assert _read_cached_artifact_index(indexes[1]) == (rows[indexes[1].resolve()],)

    assert query.call_count == 10
    _ARTIFACT_INDEX_CACHE.clear()


def test_late_index_worker_cannot_leave_a_stale_cached_generation(tmp_path) -> None:
    _ARTIFACT_INDEX_CACHE.clear()
    index = tmp_path / "index.jsonl"
    index.write_text("{}\n", encoding="utf-8")
    old_row = ArtifactFile(
        id="explicit:old",
        label="old",
        kind="image",
        path="/stored/old.png",
    )
    new_row = ArtifactFile(
        id="explicit:new",
        label="new",
        kind="image",
        path="/stored/new.png",
    )
    entered = Event()
    release = Event()
    call_lock = Lock()
    call_count = 0

    def read_index(_path):
        nonlocal call_count
        with call_lock:
            call_count += 1
            current_call = call_count
        if current_call == 1:
            entered.set()
            assert release.wait(timeout=5)
            return [old_row]
        return [new_row]

    with patch(
        "sase.core.artifact_file_query_facade.query_artifact_files",
        side_effect=read_index,
    ):
        with ThreadPoolExecutor(max_workers=1) as pool:
            old_worker = pool.submit(_read_cached_artifact_index, index)
            assert entered.wait(timeout=5)
            index.write_text('{"generation": 2}\n', encoding="utf-8")
            stat = index.stat()
            os.utime(index, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
            try:
                fresh = _read_cached_artifact_index(index)
            finally:
                release.set()
            assert old_worker.result(timeout=5) == (old_row,)
            latest = _read_cached_artifact_index(index)

    assert fresh == latest == (new_row,)
    assert call_count == 3
    _ARTIFACT_INDEX_CACHE.clear()


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


def test_bead_catalog_classifies_tasks_for_completion_detail(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sase.core.time.local_now",
        lambda: datetime(2026, 7, 31, 12, 0, 0),
    )
    root = tmp_path / "task-beads"
    root.mkdir()
    (root / "issues.jsonl").write_text("{}\n", encoding="utf-8")
    _BEAD_CACHE.pop(root.resolve(), None)
    task = Issue(
        id="sase-task.4",
        title="Complete task identity",
        status=Status.READY,
        issue_type=IssueType.TASK,
        created_at="2026-07-28T12:00:00Z",
        updated_at="2026-07-30T12:00:00Z",
    )
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
        return_value=[task],
    ):
        rows = load_bead_candidate_catalog(context).rows

    assert len(rows) == 1
    assert rows[0].payload == task.id
    assert rows[0].detail == "ready · task · ⧖ 3d"
    assert rows[0].created_at == task.created_at


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
