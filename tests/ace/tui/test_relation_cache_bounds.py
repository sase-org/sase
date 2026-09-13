"""Regressions for module-level relation caches growing unboundedly.

sase-zn.9.3 heap attribution: ``artifact_links._CACHE`` and
``link_index._INDEX_CACHE`` are keyed by a project aggregate's
``(mtime_ns, size)`` signature, which changes every time a link is created.
Before this fix neither dict ever evicted a superseded signature, so both
grew by one permanent entry per aggregate change for the life of the
process.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.relations import artifact_links as artifact_links_mod
from sase.ace.tui.relations import link_index as link_index_mod
from sase.ace.tui.relations.artifact_links import ArtifactLinksSnapshot


@pytest.fixture(autouse=True)
def _clear_relation_caches() -> None:
    artifact_links_mod._CACHE.clear()
    link_index_mod._INDEX_CACHE.clear()


def test_artifact_links_cache_stays_bounded_across_many_signatures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aggregate = tmp_path / "aggregate.json"
    monkeypatch.setattr(artifact_links_mod, "_project_keys", lambda _project: ("proj",))
    monkeypatch.setattr(
        artifact_links_mod,
        "artifact_link_aggregate_path",
        lambda _project_key: aggregate,
    )

    signature_count = artifact_links_mod._CACHE_MAX * 4
    for i in range(signature_count):
        aggregate.write_text(f'{{"schema_version": 1, "rows": [], "n": {i}}}')
        artifact_links_mod.load_artifact_links_snapshot(None)

    assert 0 < len(artifact_links_mod._CACHE) <= artifact_links_mod._CACHE_MAX


def test_link_index_cache_stays_bounded_across_many_snapshots() -> None:
    snapshot_count = link_index_mod._INDEX_CACHE_MAX * 4
    for i in range(snapshot_count):
        snapshot = ArtifactLinksSnapshot(rows=(), source_key=(("proj", i),))
        link_index_mod.link_index_for_snapshot(snapshot)

    assert 0 < len(link_index_mod._INDEX_CACHE) <= link_index_mod._INDEX_CACHE_MAX
