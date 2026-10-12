"""Tests for the archive corpus facade and its shared TUI/CLI cache."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.dismissed_bundle_index._models import DismissedBundleIndexProgress
from sase.ace.query.profile_reference_support import ProfileQueryError
from sase.core import agent_archive_corpus_cache as cache_mod
from sase.core.agent_archive_corpus_cache import (
    _archive_corpus_cache_key,
    _link_facet_signature,
    get_agent_archive_corpus,
)
from sase.core.agent_archive_facade import (
    agents_archive_profile,
    compile_agent_archive_corpus,
)
from tests._agent_archive_index_fixtures import insert_archive_rows


def _reset_archive_corpus_cache() -> None:
    cache_mod._CACHED = None
    cache_mod._GENERATION = 0


def _missing_corpus(tmp_path: Path):
    corpus = compile_agent_archive_corpus(
        root=tmp_path,
        index_status={"status": "missing"},
        timezone="America/New_York",
        link_facets={},
    )
    assert corpus.status == "missing"
    assert corpus.timezone == "America/New_York"
    assert corpus.count("") == 0
    assert len(corpus.handle) == 0
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
    assert _link_facet_signature(first) == _link_facet_signature(second)
    assert _link_facet_signature(first) != _link_facet_signature(
        {"alice": {"relations": ["other"], "artifacts": [], "count": 1}}
    )


def test_shared_cache_returns_missing_corpus_and_reuses_it(
    tmp_path: Path,
) -> None:
    _reset_archive_corpus_cache()
    try:
        progress = DismissedBundleIndexProgress(rebuilding=False, indexed_rows=0)
        first = get_agent_archive_corpus(
            root=tmp_path, progress=progress, link_facets={}
        )
        assert first.corpus.status == "missing"
        assert first.corpus.count("") == 0
        assert len(first.corpus.handle) == 0

        second = get_agent_archive_corpus(
            root=tmp_path, progress=progress, link_facets={}
        )
        assert second is first

        key = _archive_corpus_cache_key(
            index_signature=None,
            link_facets={},
            profile_digest=first.profile.digest,
        )
        assert first.key == key
    finally:
        _reset_archive_corpus_cache()


def test_shared_cache_rebuilds_after_invalidate(tmp_path: Path) -> None:
    _reset_archive_corpus_cache()
    try:
        progress = DismissedBundleIndexProgress(rebuilding=False, indexed_rows=0)
        first = get_agent_archive_corpus(
            root=tmp_path, progress=progress, link_facets={}
        )
        _reset_archive_corpus_cache()
        rebuilt = get_agent_archive_corpus(
            root=tmp_path, progress=progress, link_facets={}
        )
        assert rebuilt is not first
        assert rebuilt.key == first.key
        assert rebuilt.corpus.status == first.corpus.status
        assert rebuilt.corpus.count("") == first.corpus.count("")
        assert len(rebuilt.corpus.handle) == len(first.corpus.handle)
    finally:
        _reset_archive_corpus_cache()


def test_workflow_child_with_own_run_id_looks_up_owner(tmp_path: Path) -> None:
    insert_archive_rows(
        tmp_path,
        (
            {
                "run_id": "parent-run",
                "name": "250302.parent",
                "raw_suffix": "20260512120000",
                "status": "DONE",
                "stop_time": "2025-03-02T10:00:00Z",
            },
            {
                "run_id": "child-own-id",
                "name": "250302.step",
                "workflow_child": True,
                "parent_timestamp": "20260512120000",
            },
        ),
    )
    corpus = compile_agent_archive_corpus(
        root=tmp_path,
        index_status={"status": "ok"},
        timezone="UTC",
        link_facets={},
    )
    row = corpus.lookup("step")
    assert row is not None
    assert row["archive_key"]["source_run_id"] == "parent-run"
    assert corpus.lookup("250302.step")["archive_key"]["source_run_id"] == "parent-run"
    assert row["stop_time"] == "2025-03-02T10:00:00Z"
    assert str(row["bundle_path"]).endswith("parent-run.json")


def test_light_rows_carry_bundle_path_stop_time_and_dismissed_at(
    tmp_path: Path,
) -> None:
    insert_archive_rows(
        tmp_path,
        (
            {
                "run_id": "ended",
                "name": "250302.ended",
                "status": "DONE",
                "stop_time": "2025-03-02T11:00:00Z",
                "dismissed_at": "2025-03-02T11:30:00Z",
                "project": "sase",
            },
        ),
    )
    corpus = compile_agent_archive_corpus(
        root=tmp_path,
        index_status={"status": "ok"},
        timezone="UTC",
        link_facets={},
    )
    window = corpus.rows("", group_by="day", group_key="2025-03-02", offset=0, limit=10)
    assert window["total"] == 1
    row = window["rows"][0]
    assert row["stop_time"] == "2025-03-02T11:00:00Z"
    assert row["dismissed_at"] == "2025-03-02T11:30:00Z"
    assert str(row["bundle_path"]).endswith("ended.json")
    assert row["project"] == "sase"
