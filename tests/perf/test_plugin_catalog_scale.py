"""Fast structural tests for the plugin-catalog scale fixture and cost curves.

The slow benches record wall-clock p50/p95/max. These tests assert the
measuring stick itself: catalog sizes, the fixed filter match count, the
quadratic enrich operation curve, and fetch page counts.
"""

from __future__ import annotations

from sase.plugins.latest import enrich_with_latest
from tests.perf.plugin_catalog_scale import (
    BASELINE_PATH,
    CATALOG_SCALE_SIZES,
    FILTER_KEYSTROKE,
    FILTER_MATCH_COUNT,
    GITHUB_SEARCH_CAP_ENTRIES,
    TARGET_P95_MS,
    expected_enrich_ops,
    expected_fetch_pages,
    load_baseline,
    make_scale_catalog,
    measure_enrich_cost,
    measure_fetch_pages,
    scale_filter_match_count,
)


def _fixture_match_count(n: int) -> int:
    catalog = make_scale_catalog(n)
    needle = FILTER_KEYSTROKE
    return sum(
        1
        for entry in catalog.entries
        if needle
        in "\n".join(
            part
            for part in (entry.name, entry.repo, entry.description, *entry.topics)
            if part
        ).casefold()
    )


def test_scale_catalog_sizes_and_fixed_filter_match_count() -> None:
    for n in CATALOG_SCALE_SIZES:
        catalog = make_scale_catalog(n)
        assert len(catalog.entries) == n
        assert _fixture_match_count(n) == scale_filter_match_count(n)
    assert scale_filter_match_count(10) == 10
    assert scale_filter_match_count(250) == FILTER_MATCH_COUNT
    assert scale_filter_match_count(1000) == FILTER_MATCH_COUNT
    assert scale_filter_match_count(2000) == FILTER_MATCH_COUNT
    assert _fixture_match_count(250) == _fixture_match_count(2000)


def test_enrich_cost_curve_is_not_quadratic_in_catalog_size() -> None:
    small = measure_enrich_cost(8, runs=1, warmup=0)
    large = measure_enrich_cost(16, runs=1, warmup=0)
    assert small["fetch_calls"] == expected_enrich_ops(8)["fetch_calls"]
    assert small["installed_lookups"] == 0.0
    assert small["scan_work"] == 0.0
    assert large["fetch_calls"] == expected_enrich_ops(16)["fetch_calls"]
    assert large["installed_lookups"] == 0.0
    assert large["scan_work"] == 0.0
    thousand = expected_enrich_ops(1000)
    two_thousand = expected_enrich_ops(2000)
    assert thousand["scan_work"] == 0.0
    assert two_thousand["scan_work"] == 0.0
    assert two_thousand["fetch_calls"] / thousand["fetch_calls"] == 2.0


def test_fetch_page_count_scales_with_catalog_size_not_github_cap() -> None:
    assert expected_fetch_pages(10) == 1
    assert expected_fetch_pages(250) == 3
    assert expected_fetch_pages(1000) == 10
    assert expected_fetch_pages(2000) == 20
    assert GITHUB_SEARCH_CAP_ENTRIES / 100 == 10

    mid = measure_fetch_pages(250, runs=1, warmup=0)
    assert mid["pages"] == 3.0
    assert mid["returned_entries"] == 250.0
    small = measure_fetch_pages(10, runs=1, warmup=0)
    assert small["pages"] == 1.0
    assert small["returned_entries"] == 10.0
    over_cap = measure_fetch_pages(2000, runs=1, warmup=0)
    assert over_cap["pages"] == 20.0
    assert over_cap["returned_entries"] == 2000.0
    assert over_cap["requests"] > over_cap["pages"]


def test_committed_baseline_records_all_sizes_without_enforcing_budgets() -> None:
    baseline = load_baseline()
    assert baseline["schema_version"] == 1
    assert baseline["benchmark"] == "plugin_catalog_scale"
    assert baseline["catalog_sizes"] == list(CATALOG_SCALE_SIZES)
    assert baseline["filter_match_count"] == FILTER_MATCH_COUNT
    assert baseline["target_p95_ms"] == TARGET_P95_MS
    assert baseline["budgets_enforced"] is False
    assert BASELINE_PATH.exists()

    for n in CATALOG_SCALE_SIZES:
        key = str(n)
        enrich = baseline["enrich"][key]
        fetch = baseline["fetch"][key]
        tui = baseline["tui"][key]
        expected = expected_enrich_ops(n)
        assert enrich["fetch_calls"] == expected["fetch_calls"]
        assert enrich["installed_lookups"] == expected["installed_lookups"]
        assert enrich["scan_work"] == expected["scan_work"]
        for stat in ("p50_ms", "p95_ms", "max_ms"):
            assert enrich[stat] >= 0.0
            assert fetch[stat] >= 0.0
        assert fetch["pages"] == float(expected_fetch_pages(n))
        assert fetch["returned_entries"] == float(n)
        assert tui["filter_matches"] == float(scale_filter_match_count(n))
        for scenario in (
            "pane_open",
            "filter_keystroke",
            "j_press",
            "jump_hint",
            "install_mark",
        ):
            stats = tui[scenario]
            for stat in ("n", "p50_ms", "p95_ms", "max_ms"):
                assert stats[stat] >= 0.0


def test_enrich_with_latest_indexes_installed_versions_once() -> None:
    """Eager all-scope still fetches each miss, without a per-miss catalog scan."""
    catalog = make_scale_catalog(4)
    seen: list[str] = []

    def fetch_fn(dist_name: str) -> str:
        seen.append(dist_name)
        return "1.0.0"

    enriched = enrich_with_latest(
        catalog,
        fetch_fn=fetch_fn,
        read_cache_fn=dict,
        write_cache_fn=lambda _entries: None,
        installed_source_fn=lambda _dist: "index",
        version_records_fn=lambda: (),
        max_workers=1,
        scope="all",
    )
    assert len(seen) == 4
    assert all(entry.latest.version == "1.0.0" for entry in enriched.entries)
    assert all(entry.latest.checked for entry in enriched.entries)
