"""Tests for the archive corpus facade and its shared TUI/CLI cache."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.dismissed_bundle_index._models import DismissedBundleIndexProgress
from sase.ace.query.profile_reference_support import ProfileQueryError
from sase.core.agent_archive_corpus_cache import (
    archive_corpus_cache_key,
    get_agent_archive_corpus,
    invalidate_agent_archive_corpus_cache,
    link_facet_signature,
)
from sase.core.agent_archive_facade import (
    agents_archive_profile,
    compile_agent_archive_corpus,
)


def _missing_corpus(tmp_path: Path):
    corpus = compile_agent_archive_corpus(
        root=tmp_path,
        index_status={"status": "missing"},
        timezone="America/New_York",
        link_facets={},
    )
    assert corpus.status == "missing"
    assert corpus.timezone == "America/New_York"
    assert corpus.wire["rows"] == []
    assert not (tmp_path / "index.sqlite").exists()
    return corpus


def test_compile_missing_index_returns_empty_corpus(tmp_path: Path) -> None:
    _missing_corpus(tmp_path)


def test_corpus_query_operations_on_empty_corpus(tmp_path: Path) -> None:
    corpus = _missing_corpus(tmp_path)

    assert corpus.count("") == 0

    summary = corpus.summary("", group_by="day")
    assert summary["total"] == 0
    assert summary["groups"] == []

    window = corpus.rows("", group_by="day", group_key="2025-01-01", offset=0, limit=10)
    assert window["rows"] == []
    assert window["total"] == 0

    assert corpus.lookup("no-such-agent") is None


def test_corpus_summary_rejects_unknown_group_by(tmp_path: Path) -> None:
    corpus = _missing_corpus(tmp_path)

    with pytest.raises(ValueError, match="unsupported archive group_by"):
        corpus.summary("", group_by="century")


def test_corpus_count_rejects_unknown_field(tmp_path: Path) -> None:
    corpus = _missing_corpus(tmp_path)

    with pytest.raises(ProfileQueryError, match="bogus-field"):
        corpus.count("bogus-field:x")


def test_agents_archive_profile_digest_is_stable() -> None:
    assert agents_archive_profile().digest == agents_archive_profile().digest


def test_link_facet_signature_ignores_mapping_order() -> None:
    first = {
        "alice": {"relations": ["implements"], "artifacts": ["plan:a"], "count": 1},
        "bob": {"relations": [], "artifacts": [], "count": 0},
    }
    second = {
        "bob": {"relations": [], "artifacts": [], "count": 0},
        "alice": {"artifacts": ["plan:a"], "count": 1, "relations": ["implements"]},
    }
    assert link_facet_signature(first) == link_facet_signature(second)
    assert link_facet_signature(first) != link_facet_signature(
        {"alice": {"relations": ["other"], "artifacts": [], "count": 1}}
    )


def test_shared_cache_returns_missing_corpus_and_reuses_it(
    tmp_path: Path,
) -> None:
    invalidate_agent_archive_corpus_cache()
    try:
        progress = DismissedBundleIndexProgress(rebuilding=False, indexed_rows=0)
        first = get_agent_archive_corpus(
            root=tmp_path, progress=progress, link_facets={}
        )
        assert first.corpus.status == "missing"
        assert first.corpus.wire["rows"] == []

        second = get_agent_archive_corpus(
            root=tmp_path, progress=progress, link_facets={}
        )
        assert second is first

        key = archive_corpus_cache_key(
            index_signature=None,
            link_facets={},
            profile_digest=first.profile.digest,
        )
        assert first.key == key
    finally:
        invalidate_agent_archive_corpus_cache()


def test_shared_cache_rebuilds_after_invalidate(tmp_path: Path) -> None:
    invalidate_agent_archive_corpus_cache()
    try:
        progress = DismissedBundleIndexProgress(rebuilding=False, indexed_rows=0)
        first = get_agent_archive_corpus(
            root=tmp_path, progress=progress, link_facets={}
        )
        invalidate_agent_archive_corpus_cache()
        rebuilt = get_agent_archive_corpus(
            root=tmp_path, progress=progress, link_facets={}
        )
        assert rebuilt is not first
        assert rebuilt.key == first.key
        assert rebuilt.corpus.wire == first.corpus.wire
    finally:
        invalidate_agent_archive_corpus_cache()
