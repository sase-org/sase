"""Drive the paged (and, past the result cap, sharded) plugin catalog fetch.

This module owns the traversal policy: it pages one query explicitly (so the
timeout is per page, not a flat budget for the whole catalog), falls back to
:class:`~sase.plugins._github_source_shards.Shard` sub-queries when
``total_count`` exceeds GitHub's 1000-result cap, and unions the results into a
single de-duplicated payload list.
"""

from __future__ import annotations

import math
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sase.plugins._github_source_errors import GhNotFoundError, PluginCatalogError
from sase.plugins._github_source_gh import (
    GH_SEARCH_MAX_PAGES,
    GH_SEARCH_PER_PAGE,
    GH_SEARCH_QUERY,
    GH_SEARCH_RESULT_CAP,
    GH_TIMEOUT_SECONDS,
    RunFn,
    WhichFn,
    gh_api,
    search_endpoint,
)
from sase.plugins._github_source_parse import (
    SearchPage,
    entry_payload,
    parse_search_page,
)
from sase.plugins._github_source_shards import Shard

#: Stop sharding rather than looping if a pathological catalog fans out.
_MAX_SEARCH_REQUESTS = 200

_INCOMPLETE_RESULTS_WARNING = (
    "plugin catalog may be incomplete: GitHub search reported incomplete results"
)
_TRUNCATION_WARNING = (
    "plugin catalog is truncated: some repositories past GitHub's 1000-result "
    "search cap could not be fetched"
)
_PARTIAL_FETCH_WARNING = (
    "plugin catalog may be incomplete: a GitHub search page failed after some "
    "results were already fetched"
)


@dataclass(frozen=True)
class CatalogFetchResult:
    """Entries plus the search-envelope metadata ``fetch_catalog_payload`` saw."""

    entries: list[dict[str, Any]]
    total_count: int | None = None
    incomplete_results: bool = False
    truncated: bool = False
    warnings: tuple[str, ...] = ()


@dataclass
class _FetchState:
    entries: list[dict[str, Any]] = field(default_factory=list)
    seen: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)
    incomplete_results: bool = False
    truncated: bool = False
    reported_total: int | None = None
    requests: int = 0


def fetch_catalog_payload(
    *,
    which_fn: WhichFn = shutil.which,
    run_fn: RunFn = subprocess.run,
    timeout: float = GH_TIMEOUT_SECONDS,
    today: date | None = None,
) -> CatalogFetchResult:
    """Fetch the live plugin catalog from GitHub and return entry payloads.

    Returns a :class:`CatalogFetchResult` with canonical entry ``dict``s (see
    :func:`~sase.plugins._github_source_parse.entry_payload`) plus
    ``total_count`` / ``incomplete_results`` from the search envelope. Raises
    :class:`~sase.plugins._github_source_errors.GhNotFoundError` when ``gh`` is
    missing, :class:`~sase.plugins._github_source_errors.GhCommandError` when
    the first request fails, and
    :class:`~sase.plugins._github_source_errors.CatalogParseError` when the
    output cannot be parsed.

    Later page or shard failures degrade to a partial result with a warning
    instead of failing the whole fetch.
    """
    if which_fn("gh") is None:
        raise GhNotFoundError()

    day = date.today() if today is None else today
    state = _FetchState()
    first = _fetch_search_page(
        GH_SEARCH_QUERY,
        page=1,
        run_fn=run_fn,
        timeout=timeout,
        state=state,
        allow_cap=False,
    )
    state.reported_total = first.total_count
    _note_page_flags(state, first)
    _add_raw_items(state, first.items)

    total = first.total_count
    if total is None:
        if len(first.items) >= GH_SEARCH_PER_PAGE:
            _paginate_until_empty(
                GH_SEARCH_QUERY,
                start_page=2,
                run_fn=run_fn,
                timeout=timeout,
                state=state,
            )
        return _finalize(state)

    if total <= GH_SEARCH_RESULT_CAP:
        _paginate_query(
            GH_SEARCH_QUERY,
            start_page=2,
            total=total,
            run_fn=run_fn,
            timeout=timeout,
            state=state,
        )
        return _finalize(state)

    _collect_over_cap(
        run_fn=run_fn,
        timeout=timeout,
        today=day,
        state=state,
    )
    return _finalize(state)


def _collect_over_cap(
    *,
    run_fn: RunFn,
    timeout: float,
    today: date,
    state: _FetchState,
) -> None:
    root = Shard()
    children = root.children(today=today)
    if children is None:
        state.truncated = True
        return
    for child in children:
        _collect_shard(
            child,
            run_fn=run_fn,
            timeout=timeout,
            today=today,
            state=state,
        )


def _collect_shard(
    shard: Shard,
    *,
    run_fn: RunFn,
    timeout: float,
    today: date,
    state: _FetchState,
) -> None:
    if state.requests >= _MAX_SEARCH_REQUESTS:
        state.truncated = True
        return
    try:
        first = _fetch_search_page(
            shard.query(),
            page=1,
            run_fn=run_fn,
            timeout=timeout,
            state=state,
            allow_cap=False,
        )
    except PluginCatalogError as exc:
        _note_partial(state, exc)
        return

    _note_page_flags(state, first)
    total = first.total_count
    if total is None:
        _add_raw_items(state, first.items)
        if len(first.items) >= GH_SEARCH_PER_PAGE:
            _paginate_until_empty(
                shard.query(),
                start_page=2,
                run_fn=run_fn,
                timeout=timeout,
                state=state,
            )
        return

    if total > GH_SEARCH_RESULT_CAP:
        children = shard.children(today=today)
        if children is None:
            state.truncated = True
            _add_raw_items(state, first.items)
            _paginate_query(
                shard.query(),
                start_page=2,
                total=GH_SEARCH_RESULT_CAP,
                run_fn=run_fn,
                timeout=timeout,
                state=state,
            )
            return
        for child in children:
            _collect_shard(
                child,
                run_fn=run_fn,
                timeout=timeout,
                today=today,
                state=state,
            )
        return

    _add_raw_items(state, first.items)
    _paginate_query(
        shard.query(),
        start_page=2,
        total=total,
        run_fn=run_fn,
        timeout=timeout,
        state=state,
    )


def _paginate_query(
    query: str,
    *,
    start_page: int,
    total: int,
    run_fn: RunFn,
    timeout: float,
    state: _FetchState,
) -> None:
    pages = _page_count(total)
    for page in range(start_page, pages + 1):
        if state.requests >= _MAX_SEARCH_REQUESTS:
            state.truncated = True
            return
        try:
            parsed = _fetch_search_page(
                query,
                page=page,
                run_fn=run_fn,
                timeout=timeout,
                state=state,
                allow_cap=True,
            )
        except PluginCatalogError as exc:
            _note_partial(state, exc)
            return
        _note_page_flags(state, parsed)
        if parsed.hit_cap:
            state.truncated = True
            return
        if not parsed.items:
            return
        _add_raw_items(state, parsed.items)
        if len(parsed.items) < GH_SEARCH_PER_PAGE:
            return


def _paginate_until_empty(
    query: str,
    *,
    start_page: int,
    run_fn: RunFn,
    timeout: float,
    state: _FetchState,
) -> None:
    _paginate_query(
        query,
        start_page=start_page,
        total=GH_SEARCH_RESULT_CAP,
        run_fn=run_fn,
        timeout=timeout,
        state=state,
    )


def _fetch_search_page(
    query: str,
    *,
    page: int,
    run_fn: RunFn,
    timeout: float,
    state: _FetchState,
    allow_cap: bool,
) -> SearchPage:
    state.requests += 1
    endpoint = search_endpoint(query, page=page)
    stdout = gh_api(endpoint, run_fn=run_fn, timeout=timeout, allow_cap=allow_cap)
    if stdout is None:
        return SearchPage(items=[], hit_cap=True)
    return parse_search_page(stdout)


def _add_raw_items(state: _FetchState, raw_items: list[dict[str, Any]]) -> None:
    for raw in raw_items:
        payload = entry_payload(raw)
        key = payload["full_name"].casefold() or payload["repo"].casefold()
        if not key or key in state.seen:
            continue
        state.seen.add(key)
        state.entries.append(payload)


def _note_page_flags(state: _FetchState, page: SearchPage) -> None:
    if page.incomplete_results:
        state.incomplete_results = True
    if page.hit_cap:
        state.truncated = True


def _note_partial(state: _FetchState, exc: BaseException) -> None:
    if _PARTIAL_FETCH_WARNING not in state.warnings:
        state.warnings.append(f"{_PARTIAL_FETCH_WARNING} ({exc})")


def _finalize(state: _FetchState) -> CatalogFetchResult:
    warnings = list(state.warnings)
    if state.incomplete_results:
        warnings.append(_INCOMPLETE_RESULTS_WARNING)
    if state.truncated:
        warnings.append(_TRUNCATION_WARNING)
    return CatalogFetchResult(
        entries=state.entries,
        total_count=state.reported_total,
        incomplete_results=state.incomplete_results,
        truncated=state.truncated,
        warnings=tuple(_dedupe(warnings)),
    )


def _page_count(total: int) -> int:
    if total <= 0:
        return 0
    return min(GH_SEARCH_MAX_PAGES, math.ceil(total / GH_SEARCH_PER_PAGE))


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique
