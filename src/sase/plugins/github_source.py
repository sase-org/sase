"""Fetch the SASE plugin catalog from GitHub via the ``gh`` CLI.

The canonical registry of SASE plugins is "every GitHub repository carrying the
``sase--plugin`` topic". An authenticated ``gh api`` search returns those
repositories with their topics inline, so the catalog needs no per-repo N+1
lookups.

GitHub's REST search API hard-caps any one query at 1000 results (10 pages of
100). This module pages each query explicitly (so the timeout is per page, not
a flat 20 s for the whole catalog) and, when ``total_count`` exceeds that cap,
shards the topic search into stable ``stars:`` ranges — then ``created:`` date
ranges if a single star value still overflows — and unions the results.

This module owns only the network/parse boundary: it shells out to ``gh`` and
normalizes the raw search items into plain ``dict`` payloads (the same shape the
on-disk cache stores). Classification, installed-merge, and the public data
model live in :mod:`sase.plugins.catalog`.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

#: Topic search that defines the canonical registry. No org filter, so both
#: ``sase-org`` (built-in) and community repositories are returned.
SASE_PLUGIN_TOPIC = "sase--plugin"
GH_SEARCH_QUERY = f"topic:{SASE_PLUGIN_TOPIC}"

#: GitHub REST search returns at most this many items for any one query.
GH_SEARCH_RESULT_CAP = 1000

#: Page size used for every ``search/repositories`` request.
GH_SEARCH_PER_PAGE = 100

#: ``page=11`` is a 422; never request past this.
GH_SEARCH_MAX_PAGES = GH_SEARCH_RESULT_CAP // GH_SEARCH_PER_PAGE

#: Per-request subprocess timeout for each ``gh api`` page, in seconds.
#: Explicit paging makes the whole-catalog budget scale with page count
#: (``GH_TIMEOUT_SECONDS * pages``) instead of a flat 20 s for ``--paginate``.
GH_TIMEOUT_SECONDS = 20.0

#: Hint reused (almost) verbatim from ``sase doctor``'s GitHub plugin check.
_GH_INSTALL_HINT = (
    "Install the GitHub CLI and run `gh auth login`, then retry. "
    "See https://cli.github.com/."
)

#: Stable first-level star shards. These never become the cache key
#: (``GH_SEARCH_QUERY`` stays ``topic:sase--plugin``); adding a high-end
#: bucket later does not invalidate previously cached catalogs.
_STAR_BUCKETS: tuple[tuple[int, int | None], ...] = (
    (0, 0),
    (1, 1),
    (2, 4),
    (5, 9),
    (10, 24),
    (25, 49),
    (50, 99),
    (100, 249),
    (250, 499),
    (500, 999),
    (1000, None),
)

#: Floor used when bisecting an unbounded ``created:<DATE`` prefix.
_CREATED_FLOOR = date(2008, 1, 1)

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

WhichFn = Callable[[str], str | None]
RunFn = Callable[..., "subprocess.CompletedProcess[str]"]


class PluginCatalogError(Exception):
    """Base class for catalog-fetch failures."""


class GhNotFoundError(PluginCatalogError):
    """The ``gh`` CLI is not available on ``PATH``."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message or f"the GitHub CLI (gh) was not found on PATH. {_GH_INSTALL_HINT}"
        )


class _GhCommandError(PluginCatalogError):
    """The ``gh`` CLI ran but failed (non-zero, timeout, or OS error)."""


class _CatalogParseError(PluginCatalogError):
    """The ``gh`` output could not be parsed into catalog entries."""


@dataclass(frozen=True)
class CatalogFetchResult:
    """Entries plus the search-envelope metadata ``fetch_catalog_payload`` saw."""

    entries: list[dict[str, Any]]
    total_count: int | None = None
    incomplete_results: bool = False
    truncated: bool = False
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class _SearchPage:
    items: list[dict[str, Any]]
    total_count: int | None = None
    incomplete_results: bool = False
    hit_cap: bool = False


@dataclass(frozen=True)
class _StarRange:
    lo: int
    hi: int | None

    def qualifier(self) -> str:
        if self.hi is None:
            return f"stars:>={self.lo}"
        if self.lo == self.hi:
            return f"stars:{self.lo}"
        return f"stars:{self.lo}..{self.hi}"

    def split(self) -> tuple[_StarRange, _StarRange] | None:
        if self.hi is None:
            mid = self.lo * 2 if self.lo > 0 else 1
            if mid <= self.lo:
                return None
            return _StarRange(self.lo, mid - 1), _StarRange(mid, None)
        if self.lo >= self.hi:
            return None
        mid = (self.lo + self.hi) // 2
        return _StarRange(self.lo, mid), _StarRange(mid + 1, self.hi)


@dataclass(frozen=True)
class _CreatedRange:
    start: date | None
    end: date | None

    def qualifier(self) -> str:
        start, end = self.start, self.end
        if start is None and end is None:
            return ""
        if start is None and end is not None:
            return f"created:<{end.isoformat()}"
        if start is not None and end is None:
            return f"created:>={start.isoformat()}"
        if start is None or end is None:
            return ""
        last = end - timedelta(days=1)
        if last == start:
            return f"created:{start.isoformat()}"
        return f"created:{start.isoformat()}..{last.isoformat()}"

    def split(self, *, today: date) -> tuple[_CreatedRange, _CreatedRange] | None:
        if self.start is None and self.end is None:
            mid = date(2020, 1, 1)
            return _CreatedRange(None, mid), _CreatedRange(mid, None)
        if self.start is None:
            if self.end is None:
                return None
            return _split_created_prefix(self.end)
        if self.end is None:
            return _split_created_suffix(self.start, today=today)
        days = (self.end - self.start).days
        if days <= 1:
            return None
        mid = self.start + timedelta(days=days // 2)
        if mid <= self.start or mid >= self.end:
            return None
        return _CreatedRange(self.start, mid), _CreatedRange(mid, self.end)


@dataclass(frozen=True)
class _Shard:
    stars: _StarRange | None = None
    created: _CreatedRange | None = None

    def query(self) -> str:
        parts = [GH_SEARCH_QUERY]
        if self.stars is not None:
            parts.append(self.stars.qualifier())
        if self.created is not None:
            qualifier = self.created.qualifier()
            if qualifier:
                parts.append(qualifier)
        return " ".join(parts)

    def children(self, *, today: date) -> list[_Shard] | None:
        if self.stars is None and self.created is None:
            return [_Shard(stars=_StarRange(lo, hi)) for lo, hi in _STAR_BUCKETS]
        if self.stars is not None:
            star_split = self.stars.split()
            if star_split is not None:
                low, high = star_split
                return [
                    _Shard(stars=low, created=self.created),
                    _Shard(stars=high, created=self.created),
                ]
        created = (
            self.created if self.created is not None else _CreatedRange(None, None)
        )
        created_split = created.split(today=today)
        if created_split is None:
            return None
        earlier, later = created_split
        return [
            _Shard(stars=self.stars, created=earlier),
            _Shard(stars=self.stars, created=later),
        ]


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
    :func:`_entry_payload`) plus ``total_count`` / ``incomplete_results`` from
    the search envelope. Raises :class:`GhNotFoundError` when ``gh`` is
    missing, :class:`_GhCommandError` when the first request fails, and
    :class:`_CatalogParseError` when the output cannot be parsed.

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
    root = _Shard()
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
    shard: _Shard,
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
) -> _SearchPage:
    state.requests += 1
    endpoint = _search_endpoint(query, page=page)
    stdout = _gh_api(endpoint, run_fn=run_fn, timeout=timeout, allow_cap=allow_cap)
    if stdout is None:
        return _SearchPage(items=[], hit_cap=True)
    return _parse_search_page(stdout)


def _search_endpoint(query: str, *, page: int) -> str:
    encoded = query.replace(" ", "+")
    return f"search/repositories?q={encoded}&per_page={GH_SEARCH_PER_PAGE}&page={page}"


def _gh_api(
    endpoint: str,
    *,
    run_fn: RunFn,
    timeout: float,
    allow_cap: bool,
) -> str | None:
    try:
        result = run_fn(
            ["gh", "api", "-X", "GET", endpoint],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise _GhCommandError(
            f"`gh api` timed out after {timeout:g}s while fetching the plugin catalog."
        ) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise _GhCommandError(
            f"`gh api` could not be run: {type(exc).__name__}: {exc}"
        ) from exc

    if result.returncode != 0:
        detail = _first_nonempty_line(result.stderr, result.stdout)
        if allow_cap and _is_search_cap_error(detail):
            return None
        suffix = f": {detail}" if detail else ""
        raise _GhCommandError(
            "`gh api` failed while fetching the plugin catalog"
            f" (exit {result.returncode}){suffix}. {_GH_INSTALL_HINT}"
        )
    return result.stdout


def _is_search_cap_error(detail: str | None) -> bool:
    if not detail:
        return False
    lowered = detail.lower()
    return "only the first 1000 search results" in lowered


def _parse_search_page(stdout: str) -> _SearchPage:
    """Extract repository items and search-envelope metadata from ``gh api``.

    A single response may still be a search object, several concatenated
    per-page objects (legacy ``--paginate``), or a bare array.
    """
    text = stdout.strip()
    if not text:
        return _SearchPage(items=[], total_count=0)

    decoder = json.JSONDecoder()
    items: list[dict[str, Any]] = []
    total_count: int | None = None
    incomplete_results = False
    index = 0
    length = len(text)
    while index < length:
        while index < length and text[index].isspace():
            index += 1
        if index >= length:
            break
        try:
            value, end = decoder.raw_decode(text, index)
        except json.JSONDecodeError as exc:
            raise _CatalogParseError(
                f"could not parse `gh api` output as JSON: {exc}"
            ) from exc
        index = end
        page = _page_from_value(value)
        items.extend(page.items)
        if page.total_count is not None:
            total_count = (
                page.total_count
                if total_count is None
                else max(total_count, page.total_count)
            )
        incomplete_results = incomplete_results or page.incomplete_results
    return _SearchPage(
        items=items,
        total_count=total_count,
        incomplete_results=incomplete_results,
    )


def _page_from_value(value: Any) -> _SearchPage:
    if isinstance(value, dict):
        nested = value.get("items")
        if isinstance(nested, list):
            return _SearchPage(
                items=[item for item in nested if isinstance(item, dict)],
                total_count=_optional_int(value.get("total_count")),
                incomplete_results=value.get("incomplete_results") is True,
            )
        if "full_name" in value or "name" in value:
            return _SearchPage(items=[value])
        return _SearchPage(items=[])
    if isinstance(value, list):
        return _SearchPage(items=[item for item in value if isinstance(item, dict)])
    return _SearchPage(items=[])


def _add_raw_items(state: _FetchState, raw_items: list[dict[str, Any]]) -> None:
    for raw in raw_items:
        payload = _entry_payload(raw)
        key = payload["full_name"].casefold() or payload["repo"].casefold()
        if not key or key in state.seen:
            continue
        state.seen.add(key)
        state.entries.append(payload)


def _note_page_flags(state: _FetchState, page: _SearchPage) -> None:
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


def _split_created_prefix(end: date) -> tuple[_CreatedRange, _CreatedRange] | None:
    if end <= _CREATED_FLOOR + timedelta(days=1):
        mid = end - timedelta(days=1)
        if mid <= _CREATED_FLOOR:
            return None
        return _CreatedRange(None, mid), _CreatedRange(mid, end)
    span_days = (end - _CREATED_FLOOR).days
    mid = _CREATED_FLOOR + timedelta(days=max(span_days // 2, 1))
    if mid >= end:
        mid = end - timedelta(days=1)
    if mid <= _CREATED_FLOOR:
        return None
    return _CreatedRange(None, mid), _CreatedRange(mid, end)


def _split_created_suffix(
    start: date, *, today: date
) -> tuple[_CreatedRange, _CreatedRange] | None:
    horizon = max(today + timedelta(days=1), start + timedelta(days=2))
    mid_days = max((horizon - start).days // 2, 1)
    mid = start + timedelta(days=mid_days)
    if mid <= start:
        return None
    if mid >= horizon:
        mid = start + timedelta(days=1)
    return _CreatedRange(start, mid), _CreatedRange(mid, None)


def _entry_payload(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize one raw ``gh`` search item into a canonical entry payload."""
    repo = _str(item.get("name"))
    full_name = _str(item.get("full_name"))
    owner = _str(_get(item, "owner", "login"))
    if not owner and "/" in full_name:
        owner = full_name.split("/", 1)[0]
    if not repo and "/" in full_name:
        repo = full_name.split("/", 1)[1]
    if not full_name and owner and repo:
        full_name = f"{owner}/{repo}"

    return {
        "name": _short_name(repo),
        "repo": repo,
        "full_name": full_name,
        "owner": owner,
        "description": _str(item.get("description")),
        "url": _str(item.get("html_url")),
        "homepage": _str(item.get("homepage")),
        "topics": _str_tuple(item.get("topics")),
        "stars": _int(item.get("stargazers_count")),
        "archived": bool(item.get("archived")),
        "license": _str(_get(item, "license", "spdx_id")),
        "updated_at": _str(item.get("pushed_at")) or _str(item.get("updated_at")),
    }


def _short_name(repo: str) -> str:
    """Derive the short plugin name from a repo name (``sase-github`` -> ``github``)."""
    return repo[len("sase-") :] if repo.lower().startswith("sase-") else repo


def _get(item: dict[str, Any], *path: str) -> Any:
    value: Any = item
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _str_tuple(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    return value if isinstance(value, int) else 0


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _first_nonempty_line(*texts: str) -> str | None:
    for text in texts:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped
    return None


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


__all__ = [
    "CatalogFetchResult",
    "GH_SEARCH_PER_PAGE",
    "GH_SEARCH_QUERY",
    "GH_SEARCH_RESULT_CAP",
    "GH_TIMEOUT_SECONDS",
    "GhNotFoundError",
    "PluginCatalogError",
    "SASE_PLUGIN_TOPIC",
    "fetch_catalog_payload",
]
