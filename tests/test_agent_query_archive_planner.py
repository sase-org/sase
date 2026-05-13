"""Tests for archive-scope agent query planning."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.ace.agent_query.archive_planner import (
    ArchiveQueryError,
    archive_facet_counts,
    search_archive,
)
from sase.ace.dismissed_bundle_index import rebuild_index


def _write_bundle(root: Path, **overrides: object) -> Path:
    raw_suffix = str(overrides.get("raw_suffix", "20260512120000"))
    bundle: dict[str, object] = {
        "raw_suffix": raw_suffix,
        "agent_type": "run",
        "cl_name": "default_cl",
        "agent_name": "default_agent",
        "status": "DONE",
        "start_time": "2026-05-12T12:00:00",
        "dismissed_at": "2026-05-12T12:30:00",
        "project_file": "/tmp/projects/sase/sase.sase",
        "model": "gpt-5.5",
        "llm_provider": "codex",
        "runtime": "codex",
    }
    bundle.update(overrides)
    shard = root / raw_suffix[:6]
    shard.mkdir(parents=True, exist_ok=True)
    filename = f"{raw_suffix}.json"
    if bundle.get("step_index") is not None:
        filename = f"{raw_suffix}__c{bundle['step_index']}.json"
    path = shard / filename
    path.write_text(json.dumps(bundle), encoding="utf-8")
    return path


def test_archive_metadata_query_does_not_read_bundle_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_bundle(
        tmp_path,
        raw_suffix="20260512120000",
        cl_name="failed_cl",
        status="FAILED",
        archive_search_text="needle text",
    )
    assert rebuild_index(tmp_path).indexed_rows == 1

    def fail_read(_: Path) -> dict[str, object]:
        raise AssertionError("archive planner should not hydrate bundle JSON")

    monkeypatch.setattr("sase.ace.dismissed_bundle_index._read_bundle", fail_read)
    page = search_archive(tmp_path, "status:failed project:sase", limit=10)

    assert [row.cl_name for row in page.results] == ["failed_cl"]


def test_archive_text_query_uses_fts_projection(tmp_path: Path) -> None:
    _write_bundle(
        tmp_path,
        raw_suffix="20260512120000",
        cl_name="text_hit",
        archive_search_text="durable searchable phrase",
    )
    _write_bundle(
        tmp_path,
        raw_suffix="20260512130000",
        cl_name="text_miss",
        archive_search_text="other words",
    )
    rebuild_index(tmp_path)

    page = search_archive(tmp_path, 'text:"searchable phrase"', limit=10)

    assert [row.cl_name for row in page.results] == ["text_hit"]


def test_archive_live_only_keys_fail_loudly(tmp_path: Path) -> None:
    _write_bundle(tmp_path)
    rebuild_index(tmp_path)

    with pytest.raises(ArchiveQueryError) as exc:
        search_archive(tmp_path, "hidden:true")

    assert "only available for live agent queries" in str(exc.value)


def test_archive_query_filters_numeric_and_archive_fields(tmp_path: Path) -> None:
    _write_bundle(
        tmp_path,
        raw_suffix="20260512120000",
        cl_name="hit",
        status="FAILED",
        revived_at="2026-05-12T13:00:00",
        step_index=2,
        step_type="bash",
        retry_attempt=1,
        retry_of_timestamp="20260512110000",
        parent_timestamp="20260512100000",
        usage={"input_tokens": 800, "output_tokens": 300},
        error_message="timeout while running step",
    )
    _write_bundle(
        tmp_path,
        raw_suffix="20260512130000",
        cl_name="miss",
        status="DONE",
        step_index=1,
        step_type="python",
        retry_attempt=0,
        usage={"input_tokens": 1, "output_tokens": 2},
    )
    rebuild_index(tmp_path)

    page = search_archive(
        tmp_path,
        "revived:true step_type:bash step_index:2 retry_attempt>=1 "
        "retry_of:20260512110000 parent:20260512100000 tokens>1000 error:timeout",
        limit=10,
    )

    assert [row.cl_name for row in page.results] == ["hit"]


def test_archive_pagination_and_facets(tmp_path: Path) -> None:
    _write_bundle(
        tmp_path,
        raw_suffix="20260512120000",
        cl_name="first",
        status="FAILED",
        model="gpt-a",
        runtime="codex",
    )
    _write_bundle(
        tmp_path,
        raw_suffix="20260512130000",
        cl_name="second",
        status="DONE",
        model="gpt-b",
        runtime="codex",
    )
    rebuild_index(tmp_path)

    first_page = search_archive(tmp_path, "", limit=1)
    assert len(first_page.results) == 1
    assert first_page.next_cursor == 1
    second_page = search_archive(tmp_path, "", limit=1, cursor=first_page.next_cursor)
    assert len(second_page.results) == 1
    assert second_page.next_cursor is None
    empty_page = search_archive(tmp_path, "", limit=0)
    assert empty_page.results == []
    assert empty_page.next_cursor is None

    assert archive_facet_counts(tmp_path, "", facet="runtime") == {"codex": 2}
    assert archive_facet_counts(tmp_path, "", facet="status") == {
        "DONE": 1,
        "FAILED": 1,
    }
