"""Parse ``gh api`` search output into canonical catalog entry payloads.

This module is the pure half of the network boundary: it turns raw response
text into :class:`SearchPage` envelopes and normalizes each repository item
into the plain ``dict`` shape the on-disk cache stores.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sase.plugins._github_source_errors import CatalogParseError


@dataclass(frozen=True)
class SearchPage:
    """One page of search results plus its envelope metadata."""

    items: list[dict[str, Any]]
    total_count: int | None = None
    incomplete_results: bool = False
    hit_cap: bool = False


def parse_search_page(stdout: str) -> SearchPage:
    """Extract repository items and search-envelope metadata from ``gh api``.

    A single response may still be a search object, several concatenated
    per-page objects (legacy ``--paginate``), or a bare array.
    """
    text = stdout.strip()
    if not text:
        return SearchPage(items=[], total_count=0)

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
            raise CatalogParseError(
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
    return SearchPage(
        items=items,
        total_count=total_count,
        incomplete_results=incomplete_results,
    )


def _page_from_value(value: Any) -> SearchPage:
    if isinstance(value, dict):
        nested = value.get("items")
        if isinstance(nested, list):
            return SearchPage(
                items=[item for item in nested if isinstance(item, dict)],
                total_count=_optional_int(value.get("total_count")),
                incomplete_results=value.get("incomplete_results") is True,
            )
        if "full_name" in value or "name" in value:
            return SearchPage(items=[value])
        return SearchPage(items=[])
    if isinstance(value, list):
        return SearchPage(items=[item for item in value if isinstance(item, dict)])
    return SearchPage(items=[])


def entry_payload(item: dict[str, Any]) -> dict[str, Any]:
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
