"""Fetch the SASE plugin catalog from GitHub via the ``gh`` CLI.

The canonical registry of SASE plugins is "every GitHub repository carrying the
``sase--plugin`` topic". A single authenticated ``gh api`` search returns those
repositories with their topics inline, so the whole catalog comes from one call
with no per-repo N+1 lookups.

This module owns only the network/parse boundary: it shells out to ``gh`` and
normalizes the raw search items into plain ``dict`` payloads (the same shape the
on-disk cache stores). Classification, installed-merge, and the public data
model live in :mod:`sase.plugins.catalog`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from typing import Any

#: Topic search that defines the canonical registry. No org filter, so both
#: ``sase-org`` (built-in) and community repositories are returned.
SASE_PLUGIN_TOPIC = "sase--plugin"
GH_SEARCH_QUERY = f"topic:{SASE_PLUGIN_TOPIC}"

#: REST search endpoint path passed to ``gh api`` (topics are returned inline).
_GH_SEARCH_ENDPOINT = f"search/repositories?q={GH_SEARCH_QUERY}&per_page=100"

#: Subprocess timeout for the ``gh`` call, in seconds.
GH_TIMEOUT_SECONDS = 20.0

#: Hint reused (almost) verbatim from ``sase doctor``'s GitHub plugin check.
_GH_INSTALL_HINT = (
    "Install the GitHub CLI and run `gh auth login`, then retry. "
    "See https://cli.github.com/."
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


def fetch_catalog_payload(
    *,
    which_fn: WhichFn = shutil.which,
    run_fn: RunFn = subprocess.run,
    timeout: float = GH_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    """Fetch the live plugin catalog from GitHub and return entry payloads.

    Returns a list of canonical entry ``dict``s (see :func:`_entry_payload`).
    Raises :class:`GhNotFoundError` when ``gh`` is missing, :class:`_GhCommandError`
    when the call fails, and :class:`_CatalogParseError` when the output cannot be
    parsed.
    """
    if which_fn("gh") is None:
        raise GhNotFoundError()

    try:
        result = run_fn(
            ["gh", "api", "--paginate", "-X", "GET", _GH_SEARCH_ENDPOINT],
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
        suffix = f": {detail}" if detail else ""
        raise _GhCommandError(
            "`gh api` failed while fetching the plugin catalog"
            f" (exit {result.returncode}){suffix}. {_GH_INSTALL_HINT}"
        )

    items = _parse_search_items(result.stdout)
    return [_entry_payload(item) for item in items]


def _parse_search_items(stdout: str) -> list[dict[str, Any]]:
    """Extract repository items from ``gh api`` search output.

    ``gh api --paginate`` may emit a single search object, several concatenated
    per-page objects, or a bare array; this tolerates all three.
    """
    text = stdout.strip()
    if not text:
        return []

    decoder = json.JSONDecoder()
    items: list[dict[str, Any]] = []
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
        items.extend(_items_from_value(value))
    return items


def _items_from_value(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        nested = value.get("items")
        if isinstance(nested, list):
            return [item for item in nested if isinstance(item, dict)]
        # A bare repository object (no search envelope).
        if "full_name" in value or "name" in value:
            return [value]
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


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


def _first_nonempty_line(*texts: str) -> str | None:
    for text in texts:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped
    return None


__all__ = [
    "GH_SEARCH_QUERY",
    "GH_TIMEOUT_SECONDS",
    "GhNotFoundError",
    "PluginCatalogError",
    "SASE_PLUGIN_TOPIC",
    "fetch_catalog_payload",
]
