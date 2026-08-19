"""Shared large-catalog fixture and cost-curve helpers for plugin scale benches.

Phase ``bench`` of ``plan:202608/plugin_catalog_scale.md`` (bead ``sase-qn.1``).
The fixture is parameterized over 10 / 250 / 1000 / 2000 entries and holds the
filter match count fixed at :data:`FILTER_MATCH_COUNT` (or the full catalog when
it is smaller) so later phases can compare a clean cost curve.
"""

from __future__ import annotations

import json
import math
import statistics
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sase.plugins.catalog import PluginCatalog, PluginCatalogEntry
from sase.plugins.github_source import fetch_catalog_payload
from sase.plugins.installed import InstalledInfo
from sase.plugins.latest import LatestInfo, enrich_with_latest
from sase.plugins import latest as latest_mod

CATALOG_SCALE_SIZES: tuple[int, ...] = (10, 250, 1000, 2000)
FILTER_MATCH_COUNT = 100
FILTER_KEYSTROKE = "q"
FETCH_PAGE_SIZE = 100
GITHUB_SEARCH_CAP_ENTRIES = 1000
TARGET_P95_MS = 16.0
BASELINE_SCHEMA_VERSION = 1
BASELINE_PATH = (
    Path(__file__).resolve().parent / "baselines" / "plugin_catalog_scale_baseline.json"
)

_FETCHED_AT = 1_700_000_000.0


def scale_filter_match_count(n: int) -> int:
    """Return how many rows the scale-filter keystroke must match at size *n*."""
    return min(n, FILTER_MATCH_COUNT)


def expected_fetch_pages(n: int, *, page_size: int = FETCH_PAGE_SIZE) -> int:
    """Return how many ``per_page=100`` search pages *n* entries require."""
    if n <= 0:
        return 0
    return math.ceil(n / page_size)


def make_scale_catalog(n: int) -> PluginCatalog:
    """Build a deterministic catalog of *n* entries for the scale benches.

    The first :func:`scale_filter_match_count` names start with
    :data:`FILTER_KEYSTROKE` so one filter keystroke matches a fixed row
    count across catalog sizes. Remaining names avoid that character so the
    match set does not grow with *n*.
    """
    if n < 0:
        raise ValueError(f"catalog size must be non-negative, got {n}")
    match_count = scale_filter_match_count(n)
    entries = tuple(
        _scale_entry(index, match=index < match_count) for index in range(n)
    )
    return PluginCatalog(
        fetched_at=_FETCHED_AT,
        entries=entries,
        from_cache=True,
        stale=False,
    )


def _scale_entry(index: int, *, match: bool) -> PluginCatalogEntry:
    prefix = FILTER_KEYSTROKE if match else "p"
    name = f"{prefix}{index:04d}"
    owner = "sase-org" if index < 3 else "community-lab"
    return PluginCatalogEntry(
        name=name,
        repo=f"sase-{name}",
        full_name=f"{owner}/sase-{name}",
        owner=owner,
        description="synthetic scale catalog row",
        url=f"https://github.com/{owner}/sase-{name}",
        homepage="",
        topics=("sase--plugin",),
        stars=index,
        archived=False,
        license="MIT",
        updated_at="2026-06-01",
        installed=InstalledInfo.not_installed(),
        latest=LatestInfo.unknown(),
    )


def summarize_ms(samples: list[float]) -> dict[str, float]:
    """Return n / p50 / p95 / max for a list of millisecond samples."""
    if not samples:
        return {"n": 0.0, "p50_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0}
    ordered = sorted(samples)
    count = len(ordered)
    p95_idx = max(0, int(round(0.95 * (count - 1))))
    return {
        "n": float(count),
        "p50_ms": float(statistics.median(ordered)),
        "p95_ms": float(ordered[p95_idx]),
        "max_ms": float(ordered[-1]),
    }


def measure_enrich_cost(
    n: int,
    *,
    runs: int = 3,
    warmup: int = 1,
    clock: Callable[[], float] = time.perf_counter,
) -> dict[str, float]:
    """Time ``enrich_with_latest`` with a zero-latency ``fetch_fn``.

    Counts fetch calls and ``_installed_version_for_key`` lookups so the
    quadratic scan work (lookups × catalog size) is visible without relying
    on wall-clock noise.
    """
    catalog = make_scale_catalog(n)
    fetch_calls = 0
    lookups = 0
    original_lookup = latest_mod._installed_version_for_key

    def fetch_fn(_dist_name: str) -> str:
        nonlocal fetch_calls
        fetch_calls += 1
        return "1.0.0"

    def counting_lookup(lookup_catalog: PluginCatalog, key: str) -> str | None:
        nonlocal lookups
        lookups += 1
        return original_lookup(lookup_catalog, key)

    samples: list[float] = []
    last_fetch_calls = 0
    last_lookups = 0
    for iteration in range(warmup + runs):
        fetch_calls = 0
        lookups = 0
        with patch.object(latest_mod, "_installed_version_for_key", counting_lookup):
            started = clock()
            enrich_with_latest(
                catalog,
                fetch_fn=fetch_fn,
                read_cache_fn=dict,
                write_cache_fn=lambda _entries: None,
                clock=lambda: _FETCHED_AT,
                installed_source_fn=lambda _dist: "index",
                version_records_fn=lambda: (),
                max_workers=1,
            )
            elapsed_ms = (clock() - started) * 1000.0
        last_fetch_calls = fetch_calls
        last_lookups = lookups
        if iteration >= warmup:
            samples.append(elapsed_ms)

    stats = summarize_ms(samples)
    stats["fetch_calls"] = float(last_fetch_calls)
    stats["installed_lookups"] = float(last_lookups)
    stats["scan_work"] = float(last_lookups * n)
    return stats


def paginated_search_stdout(n: int, *, page_size: int = FETCH_PAGE_SIZE) -> str:
    """Return concatenated ``gh api --paginate`` search envelopes for *n* repos."""
    pages: list[str] = []
    for start in range(0, n, page_size):
        items = [
            _search_item(index) for index in range(start, min(start + page_size, n))
        ]
        pages.append(
            json.dumps(
                {
                    "total_count": n,
                    "incomplete_results": n > GITHUB_SEARCH_CAP_ENTRIES,
                    "items": items,
                }
            )
        )
    return "\n".join(pages)


def _search_item(index: int) -> dict[str, Any]:
    name = f"sase-plugin{index:04d}"
    return {
        "name": name,
        "full_name": f"community-lab/{name}",
        "owner": {"login": "community-lab"},
        "description": "synthetic scale catalog row",
        "html_url": f"https://github.com/community-lab/{name}",
        "homepage": "",
        "topics": ["sase--plugin"],
        "stargazers_count": index,
        "archived": False,
        "license": {"spdx_id": "MIT"},
        "pushed_at": "2026-06-01T00:00:00Z",
        "updated_at": "2026-06-01T00:00:00Z",
    }


def _run_returning(stdout: str) -> Callable[..., subprocess.CompletedProcess[str]]:
    def _run(_args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["gh"], returncode=0, stdout=stdout, stderr=""
        )

    return _run


def measure_fetch_pages(
    n: int,
    *,
    runs: int = 3,
    warmup: int = 1,
    clock: Callable[[], float] = time.perf_counter,
) -> dict[str, float]:
    """Parse *n* synthetic search items and record page count plus parse cost."""
    stdout = paginated_search_stdout(n)
    run_fn = _run_returning(stdout)
    samples: list[float] = []
    returned = 0
    for iteration in range(warmup + runs):
        started = clock()
        payload = fetch_catalog_payload(
            which_fn=lambda _name: "/usr/bin/gh",
            run_fn=run_fn,
        )
        elapsed_ms = (clock() - started) * 1000.0
        returned = len(payload)
        if iteration >= warmup:
            samples.append(elapsed_ms)
    stats = summarize_ms(samples)
    stats["pages"] = float(expected_fetch_pages(n))
    stats["returned_entries"] = float(returned)
    stats["github_search_cap_entries"] = float(GITHUB_SEARCH_CAP_ENTRIES)
    return stats


def expected_enrich_ops(n: int) -> dict[str, float]:
    """Return the current (pre-fix) enrich operation-count curve at size *n*."""
    return {
        "fetch_calls": float(n),
        "installed_lookups": float(n),
        "scan_work": float(n * n),
    }


def load_baseline(path: Path = BASELINE_PATH) -> dict[str, Any]:
    """Load the committed plugin-catalog scale baseline."""
    return json.loads(path.read_text(encoding="utf-8"))


def merge_baseline_section(
    section: str,
    payload: dict[str, Any],
    *,
    path: Path = BASELINE_PATH,
) -> dict[str, Any]:
    """Merge *payload* into one top-level baseline section and write it back."""
    baseline = load_baseline(path) if path.exists() else _empty_baseline()
    current = baseline.get(section)
    if isinstance(current, dict):
        merged = dict(current)
        merged.update(payload)
        baseline[section] = merged
    else:
        baseline[section] = payload
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
    return baseline


def _empty_baseline() -> dict[str, Any]:
    return {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "benchmark": "plugin_catalog_scale",
        "catalog_sizes": list(CATALOG_SCALE_SIZES),
        "filter_match_count": FILTER_MATCH_COUNT,
        "filter_keystroke": FILTER_KEYSTROKE,
        "target_p95_ms": TARGET_P95_MS,
        "budgets_enforced": False,
    }
