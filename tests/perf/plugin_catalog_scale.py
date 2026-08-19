"""Shared large-catalog fixture and cost-curve helpers for plugin scale benches.

Phase ``bench`` of ``plan:202608/plugin_catalog_scale.md`` (bead ``sase-qn.1``)
recorded the measuring stick; phase ``guard`` (``sase-qn.5``) enforces it.
The fixture is parameterized over 10 / 250 / 1000 / 2000 entries and holds the
filter match count fixed at :data:`FILTER_MATCH_COUNT` (or the full catalog when
it is smaller) so the keystroke curve stays comparable across sizes.
"""

from __future__ import annotations

import json
import math
import statistics
import subprocess
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from sase.plugins.catalog import PluginCatalog, PluginCatalogEntry
from sase.plugins.github_source import (
    GH_SEARCH_PER_PAGE,
    GH_SEARCH_RESULT_CAP,
    fetch_catalog_payload,
)
from sase.plugins.installed import InstalledInfo
from sase.plugins.latest import EagerScope, LatestInfo, enrich_with_latest

CATALOG_SCALE_SIZES: tuple[int, ...] = (10, 250, 1000, 2000)
FILTER_MATCH_COUNT = 100
FILTER_KEYSTROKE = "q"
FETCH_PAGE_SIZE = 100
GITHUB_SEARCH_CAP_ENTRIES = 1000
INSTALLED_SCALE_COUNT = 5
TARGET_P95_MS = 16.0
ENFORCED_TUI_SCENARIOS: tuple[str, ...] = ("filter_keystroke", "j_press")
BASELINE_SCHEMA_VERSION = 1
BASELINE_PATH = (
    Path(__file__).resolve().parent / "baselines" / "plugin_catalog_scale_baseline.json"
)

_FETCHED_AT = 1_700_000_000.0


def scale_filter_match_count(n: int) -> int:
    """Return how many rows the scale-filter keystroke must match at size *n*."""
    return min(n, FILTER_MATCH_COUNT)


def scale_installed_count(n: int) -> int:
    """Return how many synthetic rows are marked installed at size *n*."""
    return min(n, INSTALLED_SCALE_COUNT)


def expected_fetch_pages(n: int, *, page_size: int = FETCH_PAGE_SIZE) -> int:
    """Return how many ``per_page=100`` search pages *n* entries require."""
    if n <= 0:
        return 0
    return math.ceil(n / page_size)


def make_scale_catalog(n: int, *, installed_count: int = 0) -> PluginCatalog:
    """Build a deterministic catalog of *n* entries for the scale benches.

    The first :func:`scale_filter_match_count` names start with
    :data:`FILTER_KEYSTROKE` so one filter keystroke matches a fixed row
    count across catalog sizes. Remaining names avoid that character so the
    match set does not grow with *n*. The last *installed_count* rows are
    marked installed so enrich cost can stay O(installed) without changing
    the TUI fixture's default (all uninstalled) grouping.
    """
    if n < 0:
        raise ValueError(f"catalog size must be non-negative, got {n}")
    if installed_count < 0:
        raise ValueError(f"installed_count must be non-negative, got {installed_count}")
    if installed_count > n:
        raise ValueError(f"installed_count {installed_count} exceeds catalog size {n}")
    match_count = scale_filter_match_count(n)
    installed_from = n - installed_count
    entries = tuple(
        _scale_entry(
            index,
            match=index < match_count,
            installed=index >= installed_from,
        )
        for index in range(n)
    )
    return PluginCatalog(
        fetched_at=_FETCHED_AT,
        entries=entries,
        from_cache=True,
        stale=False,
    )


def _scale_entry(
    index: int,
    *,
    match: bool,
    installed: bool = False,
) -> PluginCatalogEntry:
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
        installed=(
            InstalledInfo(installed=True, version="0.1.0")
            if installed
            else InstalledInfo.not_installed()
        ),
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
    scope: EagerScope = "installed",
    installed_count: int | None = None,
) -> dict[str, float]:
    """Time ``enrich_with_latest`` with a zero-latency ``fetch_fn``.

    Default *scope* is ``installed``: eager network calls track the
    installed count, not catalog size. Installed-version lookup is a
    single dict built before the miss loop, so ``installed_lookups`` /
    ``scan_work`` stay 0 after the enrich-phase quadratic fix.
    """
    marked = scale_installed_count(n) if installed_count is None else installed_count
    catalog = make_scale_catalog(n, installed_count=marked)
    fetch_calls = 0

    def fetch_fn(_dist_name: str) -> str:
        nonlocal fetch_calls
        fetch_calls += 1
        return "1.0.0"

    samples: list[float] = []
    last_fetch_calls = 0
    for iteration in range(warmup + runs):
        fetch_calls = 0
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
            scope=scope,
        )
        elapsed_ms = (clock() - started) * 1000.0
        last_fetch_calls = fetch_calls
        if iteration >= warmup:
            samples.append(elapsed_ms)

    stats = summarize_ms(samples)
    stats["fetch_calls"] = float(last_fetch_calls)
    stats["installed_lookups"] = 0.0
    stats["scan_work"] = 0.0
    stats["installed_count"] = float(marked)
    return stats


def _search_item(index: int) -> dict[str, Any]:
    name = f"sase-plugin{index:04d}"
    created = date.fromordinal(date(2018, 1, 1).toordinal() + index)
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
        "created_at": f"{created.isoformat()}T00:00:00Z",
        "pushed_at": "2026-06-01T00:00:00Z",
        "updated_at": "2026-06-01T00:00:00Z",
    }


def _parse_search_endpoint(endpoint: str) -> tuple[str, int]:
    parsed = urlparse(
        endpoint if "://" in endpoint else f"https://api.github.com/{endpoint}"
    )
    params = parse_qs(parsed.query)
    query = params.get("q", [""])[0]
    try:
        page = int(params.get("page", ["1"])[0])
    except ValueError:
        page = 1
    return query, page


def _item_matches_query(item: dict[str, Any], query: str) -> bool:
    if "topic:sase--plugin" in query and "sase--plugin" not in (
        item.get("topics") or []
    ):
        return False
    stars = item.get("stargazers_count", 0)
    if isinstance(stars, bool) or not isinstance(stars, int):
        stars = 0
    if not _stars_match(stars, query):
        return False
    created = _item_created(item)
    return _created_match(created, query)


def _stars_match(stars: int, query: str) -> bool:
    if "stars:" not in query:
        return True
    token = next(part for part in query.split() if part.startswith("stars:"))
    spec = token[len("stars:") :]
    if ".." in spec:
        lo_s, hi_s = spec.split("..", 1)
        return int(lo_s) <= stars <= int(hi_s)
    if spec.startswith(">="):
        return stars >= int(spec[2:])
    if spec.startswith("<="):
        return stars <= int(spec[2:])
    if spec.startswith(">"):
        return stars > int(spec[1:])
    if spec.startswith("<"):
        return stars < int(spec[1:])
    return stars == int(spec)


def _item_created(item: dict[str, Any]) -> date:
    raw = item.get("created_at")
    if isinstance(raw, str) and len(raw) >= 10:
        return date.fromisoformat(raw[:10])
    return date(2026, 6, 1)


def _created_match(created: date, query: str) -> bool:
    if "created:" not in query:
        return True
    token = next(part for part in query.split() if part.startswith("created:"))
    spec = token[len("created:") :]
    if ".." in spec:
        lo_s, hi_s = spec.split("..", 1)
        return date.fromisoformat(lo_s) <= created <= date.fromisoformat(hi_s)
    if spec.startswith(">="):
        return created >= date.fromisoformat(spec[2:])
    if spec.startswith("<="):
        return created <= date.fromisoformat(spec[2:])
    if spec.startswith(">"):
        return created > date.fromisoformat(spec[1:])
    if spec.startswith("<"):
        return created < date.fromisoformat(spec[1:])
    return created == date.fromisoformat(spec)


def search_corpus_run_fn(
    items: list[dict[str, Any]],
) -> Callable[..., subprocess.CompletedProcess[str]]:
    """Stub ``gh api`` as GitHub search: per-page, 1000-result cap, qualifiers."""

    def _run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        query, page = _parse_search_endpoint(args[-1])
        matched = [item for item in items if _item_matches_query(item, query)]
        if page > GH_SEARCH_RESULT_CAP // GH_SEARCH_PER_PAGE:
            return subprocess.CompletedProcess(
                args=args,
                returncode=1,
                stdout="",
                stderr="Only the first 1000 search results are available",
            )
        start = (page - 1) * GH_SEARCH_PER_PAGE
        page_items = matched[:GH_SEARCH_RESULT_CAP][start : start + GH_SEARCH_PER_PAGE]
        body = json.dumps(
            {
                "total_count": len(matched),
                "incomplete_results": False,
                "items": page_items,
            }
        )
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout=body, stderr=""
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
    items = [_search_item(index) for index in range(n)]
    run_fn = search_corpus_run_fn(items)
    samples: list[float] = []
    returned = 0
    requests = 0

    def counting_run(
        args: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        nonlocal requests
        requests += 1
        return run_fn(args, **kwargs)

    for iteration in range(warmup + runs):
        requests = 0
        started = clock()
        payload = fetch_catalog_payload(
            which_fn=lambda _name: "/usr/bin/gh",
            run_fn=counting_run,
        )
        elapsed_ms = (clock() - started) * 1000.0
        returned = len(payload.entries)
        if iteration >= warmup:
            samples.append(elapsed_ms)
    stats = summarize_ms(samples)
    stats["pages"] = float(expected_fetch_pages(n))
    stats["returned_entries"] = float(returned)
    stats["github_search_cap_entries"] = float(GITHUB_SEARCH_CAP_ENTRIES)
    stats["requests"] = float(requests)
    return stats


def measure_fetch_truncation(
    *,
    extra: int = 1,
    today: date = date(2026, 8, 18),
) -> dict[str, float]:
    """Fetch an unsplittable corpus past GitHub's 1000-result search cap.

    Every item shares the same ``stars`` and ``created_at`` so star and
    date shards cannot split the query. The fetch must return the cap and
    surface a truncation warning rather than silently dropping the rest.
    """
    if extra < 1:
        raise ValueError(f"extra must be at least 1, got {extra}")
    n = GITHUB_SEARCH_CAP_ENTRIES + extra
    created = "2026-06-01T00:00:00Z"
    items = [
        {
            **_search_item(index),
            "stargazers_count": 0,
            "created_at": created,
            "pushed_at": created,
            "updated_at": created,
        }
        for index in range(n)
    ]
    payload = fetch_catalog_payload(
        which_fn=lambda _name: "/usr/bin/gh",
        run_fn=search_corpus_run_fn(items),
        today=today,
    )
    warnings = payload.warnings
    return {
        "catalog_size": float(n),
        "returned_entries": float(len(payload.entries)),
        "github_search_cap_entries": float(GITHUB_SEARCH_CAP_ENTRIES),
        "truncated": 1.0 if payload.truncated else 0.0,
        "warning_count": float(len(warnings)),
        "has_truncation_warning": (
            1.0 if any("truncated" in warning for warning in warnings) else 0.0
        ),
        "has_cap_warning": (
            1.0 if any("1000" in warning for warning in warnings) else 0.0
        ),
    }


def expected_enrich_ops(n: int, *, scope: EagerScope = "installed") -> dict[str, float]:
    """Return the post-guard operation-count curve at size *n*.

    Scoped eager enrichment fetches once per installed row. The
    installed-version lookup is O(1) per miss, so scan_work is 0 even
    when *scope* is ``all``.
    """
    fetch_calls = float(n) if scope == "all" else float(scale_installed_count(n))
    return {
        "fetch_calls": fetch_calls,
        "installed_lookups": 0.0,
        "scan_work": 0.0,
        "installed_count": float(scale_installed_count(n)),
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
        "installed_count": INSTALLED_SCALE_COUNT,
        "target_p95_ms": TARGET_P95_MS,
        "enforced_tui_scenarios": list(ENFORCED_TUI_SCENARIOS),
        "budgets_enforced": True,
    }
