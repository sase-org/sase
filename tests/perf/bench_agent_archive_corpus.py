"""Build and first-query budget for the compiled agent archive corpus.

Run with ``pytest -s -m slow tests/perf/bench_agent_archive_corpus.py``.
The fixture is synthetic: 11,000 top-level archive rows and 37,000 workflow
children, with no dependency on the current user's dismissed bundles.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator
from pathlib import Path
import time
from typing import Any

import pytest

from sase.core.agent_archive_facade import (
    agents_archive_profile,
    compile_agent_archive_corpus,
)
from tests._agent_archive_index_fixtures import insert_archive_rows

pytestmark = pytest.mark.slow

_TOP_LEVEL_ROWS = 11_000
_WORKFLOW_CHILD_ROWS = 37_000
_SAMPLES = 7
_BUILD_BUDGET_MS = 300.0
_QUERY_BUDGET_MS = 30.0


def test_agent_archive_corpus_build_and_first_window_budgets(
    tmp_path: Path,
) -> None:
    insert_archive_rows(tmp_path, _synthetic_rows())
    profile = agents_archive_profile()

    corpus = compile_agent_archive_corpus(
        root=tmp_path,
        index_status={"status": "ok"},
        timezone="UTC",
        link_facets={},
    )
    build_ms = [
        _measure_ms(
            lambda: compile_agent_archive_corpus(
                root=tmp_path,
                index_status={"status": "ok"},
                timezone="UTC",
                link_facets={},
            )
        )
        for _ in range(_SAMPLES)
    ]

    query_ms = [
        _measure_ms(lambda: _query_first_window(corpus, profile))
        for _ in range(_SAMPLES)
    ]
    build_p95 = _p95(build_ms)
    query_p95 = _p95(query_ms)
    print(
        "agent archive corpus benchmark: "
        f"build p95={build_p95:.1f}ms (target < {_BUILD_BUDGET_MS:.0f}ms); "
        f"query + first window p95={query_p95:.1f}ms "
        f"(target < {_QUERY_BUDGET_MS:.0f}ms)"
    )

    assert build_p95 < _BUILD_BUDGET_MS and query_p95 < _QUERY_BUDGET_MS, (
        f"build p95 {build_p95:.1f}ms, query + first-window p95 "
        f"{query_p95:.1f}ms; targets are <{_BUILD_BUDGET_MS:.0f}ms and "
        f"<{_QUERY_BUDGET_MS:.0f}ms"
    )


def _synthetic_rows() -> Iterator[dict[str, Any]]:
    for index in range(_TOP_LEVEL_ROWS):
        yield {
            "run_id": f"top-{index:05d}",
            "name": f"agent-{index:05d}",
            "status": ("DONE", "FAILED", "RUNNING")[index % 3],
            "project": ("sase", "bob", "home")[index % 3],
            "model": ("gpt-6-sol", "muse", "claude-opus")[index % 3],
            "durably_revivable": 1,
        }
    for index in range(_WORKFLOW_CHILD_ROWS):
        yield {
            "run_id": f"child-{index:05d}",
            "name": f"workflow-child-{index:05d}",
            "status": ("DONE", "FAILED", "RUNNING")[index % 3],
            "project": ("sase", "bob", "home")[index % 3],
            "model": ("gpt-6-sol", "muse", "claude-opus")[index % 3],
            "workflow_child": True,
            "durably_revivable": 1,
        }


def _query_first_window(corpus: Any, profile: Any) -> None:
    query = "outcome:failed"
    summary = corpus.summary(query, group_by="day", profile=profile)
    groups = summary.get("groups", ())
    if not groups:
        return
    corpus.rows(
        query,
        group_by="day",
        group_key=str(groups[0]["key"]),
        offset=0,
        limit=40,
        profile=profile,
    )


def _measure_ms(action: Callable[[], object]) -> float:
    started = time.perf_counter()
    action()
    return (time.perf_counter() - started) * 1_000


def _p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


__all__ = ["test_agent_archive_corpus_build_and_first_window_budgets"]
