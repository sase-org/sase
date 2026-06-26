"""PyPI lookup for latest SASE plugin versions.

``sase plugin list`` and ``sase plugin show`` use the package index as the
source of truth for "latest available" because ``sase plugin update`` resolves
from the index. This module is deliberately tiny and injectable so tests never
touch the real network.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

PYPI_JSON_BASE_URL = "https://pypi.org/pypi"
DEFAULT_TIMEOUT_SECONDS = 2.0

UrlOpenFn = Callable[..., Any]


def fetch_latest_version(
    dist_name: str,
    *,
    urlopen_fn: UrlOpenFn = urllib.request.urlopen,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> str | None:
    """Return PyPI's ``info.version`` for *dist_name*, or ``None`` on failure."""
    quoted = urllib.parse.quote(dist_name.strip(), safe="")
    if not quoted:
        return None
    request = urllib.request.Request(
        f"{PYPI_JSON_BASE_URL}/{quoted}/json",
        headers={"Accept": "application/json", "User-Agent": "sase"},
    )

    try:
        with urlopen_fn(request, timeout=timeout) as response:  # noqa: S310
            raw = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        return None
    except (OSError, TimeoutError, ValueError):
        return None

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    info = payload.get("info")
    if not isinstance(info, dict):
        return None
    version = info.get("version")
    return version if isinstance(version, str) and version else None


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "PYPI_JSON_BASE_URL",
    "fetch_latest_version",
]
