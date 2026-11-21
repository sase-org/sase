"""Paging and filtering contract of the recency-bounded index reads."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

import sase.core.agent_artifact_index_recent as recent

FLOOR = 1_000.0


def _row(name: str, finished: float | None) -> dict[str, Any]:
    done: dict[str, Any] = {"outcome": "failed" if "fail" in name else "completed"}
    if finished is not None:
        done["finished_at"] = finished
    return {"artifact_dir": f"/a/{name}", "done": done}


class _FakeIndex:
    """Serve the completed tier newest-first, like sase-core's completed query."""

    def __init__(
        self, rows: list[dict[str, Any]], *, dropped_after_decode: int = 0
    ) -> None:
        self.rows = rows
        self.dropped_after_decode = dropped_after_decode
        self.limits: list[int] = []

    def __call__(
        self, _index: Any, _root: Any, query: Any, _options: Any
    ) -> Mapping[str, Any]:
        assert not query.include_active
        assert not query.include_full_history
        assert query.include_recent_completed
        self.limits.append(query.recent_completed_limit)
        page = self.rows[: query.recent_completed_limit]
        kept = page[: max(0, len(page) - self.dropped_after_decode)]
        return {
            "records": kept,
            "stats": {"record_json_decoded": len(page), "json_decode_errors": 0},
        }


def _install(monkeypatch: pytest.MonkeyPatch, fake: _FakeIndex) -> None:
    monkeypatch.setattr(recent, "query_agent_artifact_index_payload", fake)


def _read(**kwargs: Any) -> list[str]:
    records = recent.query_recently_completed_payload_records(
        "/index", "/projects", finished_after=FLOOR, **kwargs
    )
    return [str(record["artifact_dir"]).rsplit("/", 1)[-1] for record in records]


def test_pages_double_until_a_row_finished_before_the_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [_row(f"r{i}", 2_000.0 - i) for i in range(9)] + [_row("old", 10.0)]
    fake = _FakeIndex(rows)
    _install(monkeypatch, fake)

    names = _read(first_page=2)

    assert fake.limits == [2, 4, 8, 16]
    assert names == [f"r{i}" for i in range(9)]


def test_exhausted_tier_stops_after_one_short_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeIndex([_row("a", 3_000.0), _row("b", 2_000.0)])
    _install(monkeypatch, fake)

    assert _read(first_page=8) == ["a", "b"]
    assert fake.limits == [8]


def test_rows_without_finished_at_never_end_paging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [_row("a", 3_000.0), _row("unstamped", None), _row("b", 2_000.0)]
    rows += [_row("c", 1_500.0), _row("old", 500.0)]
    fake = _FakeIndex(rows)
    _install(monkeypatch, fake)

    assert _read(first_page=2) == ["a", "unstamped", "b", "c"]
    assert fake.limits == [2, 4, 8]


def test_rows_dropped_after_decode_do_not_end_paging_early(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [_row(f"r{i}", 3_000.0 - i) for i in range(6)] + [_row("old", 1.0)]
    fake = _FakeIndex(rows, dropped_after_decode=1)
    _install(monkeypatch, fake)

    names = _read(first_page=2)

    # Each page loses its last decoded row, yet the SQL page was full, so
    # paging continues until the tier runs out.
    assert fake.limits == [2, 4, 8]
    assert names == [f"r{i}" for i in range(6)]


def test_keep_filters_returned_rows_but_not_paging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [_row("fail-a", 3_000.0), _row("ok-b", 2_000.0), _row("ok-old", 1.0)]
    fake = _FakeIndex(rows)
    _install(monkeypatch, fake)

    names = _read(
        first_page=2,
        keep=lambda record: record["done"]["outcome"] == "failed",
    )

    assert names == ["fail-a"]
    assert fake.limits == [2, 4]


def test_query_index_payload_records_applies_keep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def payload(*_args: Any) -> Mapping[str, Any]:
        return {"records": [_row("fail-a", 1.0), _row("ok-b", 2.0), "junk"]}

    monkeypatch.setattr(recent, "query_agent_artifact_index_payload", payload)

    records = recent.query_index_payload_records(
        "/index",
        "/projects",
        recent.AgentArtifactIndexQueryWire(),
        keep=lambda record: record["done"]["outcome"] == "failed",
    )

    assert [record["artifact_dir"] for record in records] == ["/a/fail-a"]
