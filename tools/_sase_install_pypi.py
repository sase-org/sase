#!/usr/bin/env python3
"""A tiny PyPI JSON client for the ``sase_install`` engine (stdlib-only).

Only two questions are answered: the latest published version of a
distribution, and whether the distribution is published at all. Network trouble
is reported as data (``warning``), never raised: dry runs degrade to a ``⚠``
row while real runs treat it as a preflight failure.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass


#: Timeout for every PyPI metadata request, per the engine contract.
PYPI_TIMEOUT_SECONDS = 5.0

_PYPI_URL_TEMPLATE = "https://pypi.org/pypi/{name}/json"

_VERSION_CHUNK_RE = re.compile(r"\d+|[a-zA-Z]+")


@dataclass(frozen=True)
class PypiInfo:
    """What PyPI says about one distribution name."""

    name: str
    published: bool | None
    version: str | None = None
    warning: str | None = None


def fetch_pypi_info(
    name: str,
    *,
    timeout: float = PYPI_TIMEOUT_SECONDS,
    opener: Callable[[str, float], object] | None = None,
) -> PypiInfo:
    """Return the latest published version of *name*, or why it is unknown."""
    try:
        if opener is not None:
            payload = opener(name, timeout)
        else:
            payload = _default_fetch(name, timeout)
    except _NotPublished:
        return PypiInfo(name=name, published=False)
    except (OSError, ValueError) as exc:
        return PypiInfo(
            name=name,
            published=None,
            warning=f"could not reach PyPI for {name}: {exc}",
        )
    if not isinstance(payload, dict):
        return PypiInfo(
            name=name,
            published=None,
            warning=f"could not reach PyPI for {name}: unexpected response",
        )
    info = payload.get("info")
    version = info.get("version") if isinstance(info, dict) else None
    if not isinstance(version, str) or not version:
        return PypiInfo(
            name=name,
            published=None,
            warning=f"could not reach PyPI for {name}: missing version",
        )
    return PypiInfo(name=name, published=True, version=version)


class _NotPublished(Exception):
    """The PyPI JSON API answered 404: this name is not published."""


def _default_fetch(name: str, timeout: float) -> object:
    url = _PYPI_URL_TEMPLATE.format(name=name)
    request = urllib.request.Request(
        url, headers={"User-Agent": "sase-installer/1", "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise _NotPublished(name) from exc
        raise OSError(f"HTTP {exc.code} from PyPI") from exc
    except urllib.error.URLError as exc:
        raise OSError(exc.reason) from exc


def _version_key(version: str) -> tuple[tuple[int, object], ...]:
    """Return a sortable key for a version string (PEP 440-flavored subset).

    Numeric chunks sort numerically and ``post`` sorts after them, while other
    letter chunks (``dev``, ``rc``, ``a``, ``b``) sort before them. A missing
    numeric tail (``1.2`` vs ``1.2.0``) compares equal after zero-padding. This
    is not a full PEP 440 implementation, but it orders the ``X.Y.Z`` releases
    the installer compares.
    """
    chunks: list[tuple[int, object]] = []
    for chunk in _VERSION_CHUNK_RE.findall(version):
        if chunk.isdigit():
            chunks.append((1, int(chunk)))
        elif chunk.lower() == "post":
            chunks.append((2, "post"))
        else:
            chunks.append((0, chunk.lower()))
    return tuple(chunks)


def _pad_pair(
    left: tuple[tuple[int, object], ...], right: tuple[tuple[int, object], ...]
) -> tuple[tuple[tuple[int, object], ...], tuple[tuple[int, object], ...]]:
    width = max(len(left), len(right))
    return (
        tuple(list(left) + [(1, 0)] * (width - len(left))),
        tuple(list(right) + [(1, 0)] * (width - len(right))),
    )


def compare_versions(current: str, target: str) -> int:
    """Return -1/0/+1 when *current* is older/equal/newer than *target*."""
    left, right = _pad_pair(
        _version_key(current.strip()), _version_key(target.strip())
    )
    if left == right:
        return 0
    return -1 if left < right else 1


def versions_equal(current: str, target: str) -> bool:
    """Return whether two version strings name the same release."""
    return compare_versions(current, target) == 0


__all__ = [
    "PYPI_TIMEOUT_SECONDS",
    "PypiInfo",
    "compare_versions",
    "fetch_pypi_info",
    "versions_equal",
]
