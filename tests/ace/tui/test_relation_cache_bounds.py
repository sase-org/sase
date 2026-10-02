"""Regressions for module-level relation caches growing unboundedly.

``artifact_links._CACHE`` and ``link_index._INDEX_CACHE`` are keyed by
project scope with the aggregate ``(mtime_ns, size)`` signature stored
alongside the value. A changed stat or signature replaces the scope's entry
instead of piling up one permanent entry per superseded version
(sase-1ez.3 snapshot-caches; see also sase-zn.9.3 heap attribution).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.ace.tui.relations import artifact_links as artifact_links_mod
from sase.ace.tui.relations import link_index as link_index_mod
from sase.ace.tui.relations.artifact_links import ArtifactLinksSnapshot
from sase.sdd._artifact_link_store_support import ARTIFACT_LINK_ROW_SCHEMA_VERSION


@pytest.fixture(autouse=True)
def _clear_relation_caches():
    artifact_links_mod._CACHE.clear()
    link_index_mod._INDEX_CACHE.clear()
    yield
    artifact_links_mod._CACHE.clear()
    link_index_mod._INDEX_CACHE.clear()


def _patch_single_project(
    monkeypatch: pytest.MonkeyPatch, aggregate: Path, project: str = "proj"
) -> None:
    monkeypatch.setattr(artifact_links_mod, "_project_keys", lambda _p: (project,))
    monkeypatch.setattr(
        artifact_links_mod,
        "artifact_link_aggregate_path",
        lambda _project_key: aggregate,
    )


def _write_aggregate(aggregate: Path, n: int) -> None:
    payload = {
        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
        "rows": [],
        "n": n,
        "pad": "x" * n,
    }
    aggregate.write_text(json.dumps(payload), encoding="utf-8")


def test_artifact_links_replaces_entry_across_external_rewrites(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aggregate = tmp_path / "aggregate.json"
    _patch_single_project(monkeypatch, aggregate)

    rewrites = 32
    for i in range(rewrites):
        _write_aggregate(aggregate, i)
        artifact_links_mod.load_artifact_links_snapshot(None)

    assert len(artifact_links_mod._CACHE) == 1
    assert list(artifact_links_mod._CACHE) == [("proj",)]


def test_artifact_links_cache_stays_bounded_across_many_scopes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        artifact_links_mod,
        "artifact_link_aggregate_path",
        lambda project_key: tmp_path / f"{project_key}.json",
    )
    scope_count = artifact_links_mod._CACHE_MAX * 4
    for i in range(scope_count):
        project = f"proj-{i}"
        monkeypatch.setattr(
            artifact_links_mod, "_project_keys", lambda _p, _proj=project: (_proj,)
        )
        _write_aggregate(tmp_path / f"{project}.json", i)
        artifact_links_mod.load_artifact_links_snapshot(None)

    assert 0 < len(artifact_links_mod._CACHE) <= artifact_links_mod._CACHE_MAX


def test_artifact_links_stale_signature_is_never_served(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aggregate = tmp_path / "aggregate.json"
    _patch_single_project(monkeypatch, aggregate)

    _write_aggregate(aggregate, 1)
    first = artifact_links_mod.load_artifact_links_snapshot(None)
    _write_aggregate(aggregate, 2)
    second = artifact_links_mod.load_artifact_links_snapshot(None)
    assert second.source_key != first.source_key
    # Callers holding the older snapshot keep using it; the cache pins live.
    assert first.source_key != second.source_key

    # Simulate a slow worker publishing its older signature after the newer
    # one landed: it only costs a reload, never a mismatched serve.
    with artifact_links_mod._CACHE_LOCK:
        artifact_links_mod._CACHE[("proj",)] = (first.source_key, first)
    third = artifact_links_mod.load_artifact_links_snapshot(None)
    assert third.source_key == second.source_key
    assert third is second or third == second


def test_link_index_replaces_entry_across_signature_changes() -> None:
    for i in range(32):
        snapshot = ArtifactLinksSnapshot(rows=(), source_key=(("proj", i, 10 + i),))
        link_index_mod.link_index_for_snapshot(snapshot)

    assert len(link_index_mod._INDEX_CACHE) == 1
    assert list(link_index_mod._INDEX_CACHE) == [("proj",)]


def test_link_index_cache_stays_bounded_across_many_scopes() -> None:
    scope_count = link_index_mod._INDEX_CACHE_MAX * 4
    for i in range(scope_count):
        snapshot = ArtifactLinksSnapshot(rows=(), source_key=((f"proj-{i}", 1, 2),))
        link_index_mod.link_index_for_snapshot(snapshot)

    assert 0 < len(link_index_mod._INDEX_CACHE) <= link_index_mod._INDEX_CACHE_MAX


def test_link_index_stale_source_key_is_never_served() -> None:
    newer = ArtifactLinksSnapshot(rows=(), source_key=(("proj", 2, 20),))
    link_index_mod.link_index_for_snapshot(newer)
    older = ArtifactLinksSnapshot(rows=(), source_key=(("proj", 1, 10),))
    older_index = link_index_mod.link_index_for_snapshot(older)
    # A slower worker publishing an older signature replaces the entry...
    assert link_index_mod._INDEX_CACHE[("proj",)][0] == older.source_key
    # ...but a lookup for the newer key never gets the older index back.
    served = link_index_mod.link_index_for_snapshot(newer)
    assert served.source_key == newer.source_key
    assert served is not older_index
    assert link_index_mod._INDEX_CACHE[("proj",)][0] == newer.source_key


def test_link_index_empty_snapshot_scope() -> None:
    snapshot = ArtifactLinksSnapshot(rows=(), source_key=())
    link_index_mod.link_index_for_snapshot(snapshot)
    assert list(link_index_mod._INDEX_CACHE) == [()]
