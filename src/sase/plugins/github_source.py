"""Fetch the SASE plugin catalog from GitHub via the ``gh`` CLI.

The canonical registry of SASE plugins is "every GitHub repository carrying the
``sase--plugin`` topic". An authenticated ``gh api`` search returns those
repositories with their topics inline, so the catalog needs no per-repo N+1
lookups.

GitHub's REST search API hard-caps any one query at 1000 results (10 pages of
100). The fetch driver pages each query explicitly (so the timeout is per page,
not a flat 20 s for the whole catalog) and, when ``total_count`` exceeds that
cap, shards the topic search into stable ``stars:`` ranges — then ``created:``
date ranges if a single star value still overflows — and unions the results.

This module is the stable public import surface for that boundary; it owns only
the network/parse edge and normalizes raw search items into plain ``dict``
payloads (the same shape the on-disk cache stores). The implementation is split
across private sibling modules:

* :mod:`sase.plugins._github_source_errors` — the failure hierarchy.
* :mod:`sase.plugins._github_source_gh` — search constants and the ``gh api``
  subprocess call.
* :mod:`sase.plugins._github_source_parse` — JSON envelopes and entry payloads.
* :mod:`sase.plugins._github_source_shards` — over-cap query sharding.
* :mod:`sase.plugins._github_source_fetch` — the paging/sharding driver.

Classification, installed-merge, and the public data model live in
:mod:`sase.plugins.catalog`.
"""

from __future__ import annotations

from ._github_source_errors import (
    CatalogParseError,
    GhCommandError,
    GhNotFoundError,
    PluginCatalogError,
)
from ._github_source_fetch import CatalogFetchResult, fetch_catalog_payload
from ._github_source_gh import (
    GH_SEARCH_PER_PAGE,
    GH_SEARCH_QUERY,
    GH_SEARCH_RESULT_CAP,
    GH_TIMEOUT_SECONDS,
    SASE_PLUGIN_TOPIC,
)

__all__ = [
    "CatalogFetchResult",
    "CatalogParseError",
    "GH_SEARCH_PER_PAGE",
    "GH_SEARCH_QUERY",
    "GH_SEARCH_RESULT_CAP",
    "GH_TIMEOUT_SECONDS",
    "GhCommandError",
    "GhNotFoundError",
    "PluginCatalogError",
    "SASE_PLUGIN_TOPIC",
    "fetch_catalog_payload",
]
