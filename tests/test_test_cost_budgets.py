"""Unit tests for suite cost budget enforcement."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tests._test_cost import build_cost_record, check_cost_budgets


def test_cost_budget_check_reports_regressions() -> None:
    record = build_cost_record(
        [
            {
                "worker_id": "gw0",
                "wall_seconds": 1.0,
                "cpu_seconds": 0.25,
                "collection_seconds": 2.0,
                "peak_rss_kib": 100,
                "causes": {"parser_create": {"count": 1, "seconds": 1.25}},
                "files": {
                    "tests/test_a.py": {
                        "node_count": 1,
                        "wall_seconds": 3.0,
                        "cpu_seconds": 1.0,
                        "causes": {"parser_create": {"count": 1, "seconds": 1.25}},
                    }
                },
            }
        ],
        mode="cost",
        worker_count=1,
        host="host",
        now=datetime(2026, 8, 9, tzinfo=UTC),
    )
    budgets = {
        "schema": 1,
        "tolerance": {"local": 0.10},
        "summary": {"total_file_wall_seconds": {"limit": 2.0}},
        "causes": {"parser_create": {"limit": 1.0}},
    }

    failures = check_cost_budgets(record, budgets)

    assert [failure.metric for failure in failures] == [
        "total_file_wall_seconds",
        "causes.parser_create",
    ]
    assert failures[0].allowed == 2.2


def test_cost_budget_check_uses_wider_ci_tolerance() -> None:
    record = build_cost_record(
        [
            {
                "worker_id": "gw0",
                "wall_seconds": 1.0,
                "cpu_seconds": 1.0,
                "collection_seconds": 11.5,
                "peak_rss_kib": 100,
                "causes": {},
                "files": {},
            }
        ],
        mode="cost",
        worker_count=1,
        host="host",
        now=datetime(2026, 8, 9, tzinfo=UTC),
    )
    budgets = {
        "schema": 1,
        "tolerance": {"local": 0.10, "ci": 0.20},
        "summary": {"collection_seconds": {"limit": 10.0}},
        "causes": {},
    }

    assert check_cost_budgets(record, budgets)
    assert check_cost_budgets(record, budgets, ci=True) == []


def test_check_cost_budgets_classifies_severity_by_family() -> None:
    record = {
        "summary": {
            "total_file_wall_seconds": 100.0,
            "total_file_cpu_seconds": 100.0,
            "peak_worker_rss_kib": 100.0,
            "causes": {
                "some_cause": {"count": 10, "seconds": 100.0, "cpu_seconds": 100.0},
            },
        },
    }
    budgets = {
        "schema": 1,
        "tolerance": {"local": 0.0, "ci": 0.0, "cpu": 0.0},
        "summary": {
            "total_file_wall_seconds": {"limit": 1.0},
            "total_file_cpu_seconds": {"limit": 1.0},
            "peak_worker_rss_kib": {"limit": 1.0},
        },
        "causes": {
            "some_cause": {"limit": 1.0, "cpu_limit": 1.0, "count_limit": 1},
        },
    }

    failures = {
        failure.metric: failure for failure in check_cost_budgets(record, budgets)
    }

    assert failures["total_file_wall_seconds"].severity == "advisory"
    assert failures["total_file_cpu_seconds"].severity == "hard"
    assert failures["peak_worker_rss_kib"].severity == "hard"
    assert failures["causes.some_cause"].severity == "advisory"
    assert failures["causes.some_cause.cpu"].severity == "hard"
    assert failures["causes.some_cause.count"].severity == "hard"


def test_check_cost_budgets_enforce_overrides_family_default() -> None:
    record = {"summary": {"total_file_wall_seconds": 100.0}}
    budgets = {
        "schema": 1,
        "tolerance": {"local": 0.0},
        "summary": {"total_file_wall_seconds": {"limit": 1.0, "enforce": "hard"}},
        "causes": {},
    }

    failures = check_cost_budgets(record, budgets)

    assert failures[0].severity == "hard"


def test_count_budget_has_no_tolerance() -> None:
    record = {
        "summary": {"causes": {"c": {"count": 10, "seconds": 0.0, "cpu_seconds": 0.0}}}
    }
    budgets = {
        "schema": 1,
        "tolerance": {"local": 0.5, "cpu": 0.5},
        "summary": {},
        "causes": {"c": {"count_limit": 10}},
    }

    assert check_cost_budgets(record, budgets) == []

    budgets["causes"]["c"]["count_limit"] = 9
    failures = check_cost_budgets(record, budgets)

    assert failures[0].metric == "causes.c.count"
    assert failures[0].tolerance == 0.0
    assert failures[0].allowed == 9.0


def test_cpu_budget_uses_cpu_tolerance() -> None:
    record = {
        "summary": {"causes": {"c": {"count": 1, "seconds": 0.0, "cpu_seconds": 11.5}}}
    }
    budgets = {
        "schema": 1,
        "tolerance": {"cpu": 0.10},
        "summary": {},
        "causes": {"c": {"cpu_limit": 10.0}},
    }

    failures = check_cost_budgets(record, budgets)

    assert failures[0].metric == "causes.c.cpu"
    assert failures[0].tolerance == 0.10
    assert failures[0].allowed == pytest.approx(11.0)


def test_per_worker_normalization_divides_summed_actual_by_worker_count() -> None:
    record = {"summary": {"collection_cpu_seconds": 160.0}, "worker_count": 10}
    budgets = {
        "schema": 1,
        "tolerance": {"local": 0.0, "cpu": 0.0},
        "summary": {"collection_cpu_seconds": {"limit": 20.0, "per_worker": True}},
        "causes": {},
    }

    assert check_cost_budgets(record, budgets) == []

    budgets["summary"]["collection_cpu_seconds"]["limit"] = 15.0
    failures = check_cost_budgets(record, budgets)

    assert [failure.metric for failure in failures] == [
        "collection_cpu_seconds (per worker)"
    ]
    assert failures[0].actual == pytest.approx(16.0)


def test_per_worker_normalization_falls_back_when_worker_count_is_null() -> None:
    record = {
        "summary": {"collection_seconds": 40.0},
        "worker_count": None,
        "workers": [{"collection_seconds": 5.0}, {"collection_seconds": 5.0}],
    }
    budgets = {
        "schema": 1,
        "tolerance": {"local": 0.0},
        "summary": {"collection_seconds": {"limit": 20.0, "per_worker": True}},
        "causes": {},
    }

    assert check_cost_budgets(record, budgets) == []


def test_per_worker_normalization_never_divides_by_zero() -> None:
    record = {
        "summary": {"collection_seconds": 12.0},
        "worker_count": None,
        "workers": [],
    }
    budgets = {
        "schema": 1,
        "tolerance": {"local": 0.0},
        "summary": {"collection_seconds": {"limit": 12.0, "per_worker": True}},
        "causes": {},
    }

    assert check_cost_budgets(record, budgets) == []
