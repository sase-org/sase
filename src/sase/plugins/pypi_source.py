"""PyPI lookup for latest SASE plugin versions and catalog availability.

``sase plugin list`` and ``sase plugin show`` use the package index as the
source of truth for "latest available" because ``sase plugin update`` resolves
from the index. Catalog install planning also probes here to decide whether a
plugin should fall back to its git repository (see :class:`ProjectAvailability`).
This module is deliberately tiny and injectable so tests never touch the real
network.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from enum import Enum
from typing import Any

PYPI_JSON_BASE_URL = "https://pypi.org/pypi"
DEFAULT_TIMEOUT_SECONDS = 2.0
DEFAULT_BATCH_MAX_WORKERS = 8
DEFAULT_BATCH_DEADLINE_SECONDS = 8.0

UrlOpenFn = Callable[..., Any]


class ProjectAvailability(Enum):
    """Whether a public PyPI probe definitively resolved a distribution.

    Only ``MISSING`` (an HTTP 404) permits an automatic git fallback.
    ``UNAVAILABLE`` covers every other failure — timeout, transport error,
    malformed JSON, offline operation — so a PyPI outage is never confused
    with a definitive absence.
    """

    AVAILABLE = "available"
    MISSING = "missing"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class _ProjectProbeResult:
    """The typed result of probing one distribution name against public PyPI."""

    status: ProjectAvailability
    version: str | None = None


def _probe_project(
    dist_name: str,
    *,
    urlopen_fn: UrlOpenFn = urllib.request.urlopen,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> _ProjectProbeResult:
    """Probe public PyPI for *dist_name* and return a typed result."""
    quoted = urllib.parse.quote(dist_name.strip(), safe="")
    if not quoted:
        return _ProjectProbeResult(status=ProjectAvailability.UNAVAILABLE)
    request = urllib.request.Request(
        f"{PYPI_JSON_BASE_URL}/{quoted}/json",
        headers={"Accept": "application/json", "User-Agent": "sase"},
    )

    try:
        with urlopen_fn(request, timeout=timeout) as response:  # noqa: S310
            raw = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return _ProjectProbeResult(status=ProjectAvailability.MISSING)
        return _ProjectProbeResult(status=ProjectAvailability.UNAVAILABLE)
    except (OSError, TimeoutError, ValueError):
        return _ProjectProbeResult(status=ProjectAvailability.UNAVAILABLE)

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return _ProjectProbeResult(status=ProjectAvailability.UNAVAILABLE)
    if not isinstance(payload, dict):
        return _ProjectProbeResult(status=ProjectAvailability.UNAVAILABLE)
    info = payload.get("info")
    if not isinstance(info, dict):
        return _ProjectProbeResult(status=ProjectAvailability.UNAVAILABLE)
    version = info.get("version")
    version = version if isinstance(version, str) and version else None
    return _ProjectProbeResult(status=ProjectAvailability.AVAILABLE, version=version)


def probe_availability(
    dist_name: str,
    *,
    urlopen_fn: UrlOpenFn = urllib.request.urlopen,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> ProjectAvailability:
    """Return only the availability status for *dist_name*.

    The default ``availability_fn`` for single-plugin install planning.
    """
    return _probe_project(dist_name, urlopen_fn=urlopen_fn, timeout=timeout).status


def probe_availability_many(
    dist_names: Sequence[str],
    *,
    probe_fn: Callable[[str], ProjectAvailability] = probe_availability,
    max_workers: int = DEFAULT_BATCH_MAX_WORKERS,
    deadline_seconds: float = DEFAULT_BATCH_DEADLINE_SECONDS,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, ProjectAvailability]:
    """Probe every distinct name in *dist_names* under one shared time budget.

    Batch install planning (marked-set ACE installs, required-plugin gates)
    must not multiply :data:`DEFAULT_TIMEOUT_SECONDS` by the number of
    plugins being planned. A bounded worker pool plus one overall
    *deadline_seconds* keeps N plugins within one fixed budget. A name that
    does not finish before the deadline is simply absent from the result, so
    callers should treat a missing key as :attr:`ProjectAvailability.UNAVAILABLE`.
    """
    unique = sorted(set(dist_names))
    if not unique:
        return {}
    if len(unique) == 1:
        return {unique[0]: probe_fn(unique[0])}

    started = monotonic()
    workers = max(1, min(max_workers, len(unique)))
    results: dict[str, ProjectAvailability] = {}
    executor = ThreadPoolExecutor(max_workers=workers)
    try:
        futures = {executor.submit(probe_fn, name): name for name in unique}
        pending = set(futures)
        while pending:
            remaining = max(0.0, deadline_seconds - (monotonic() - started))
            if remaining <= 0:
                for future in pending:
                    future.cancel()
                break
            done, pending = wait(
                pending, timeout=remaining, return_when=FIRST_COMPLETED
            )
            if not done:
                for future in pending:
                    future.cancel()
                break
            for future in done:
                name = futures[future]
                try:
                    results[name] = future.result()
                except Exception:  # noqa: BLE001 - one failed probe must not sink the batch.
                    results[name] = ProjectAvailability.UNAVAILABLE
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return results


def fetch_latest_version(
    dist_name: str,
    *,
    urlopen_fn: UrlOpenFn = urllib.request.urlopen,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> str | None:
    """Return PyPI's ``info.version`` for *dist_name*, or ``None`` on failure."""
    return _probe_project(dist_name, urlopen_fn=urlopen_fn, timeout=timeout).version


__all__ = [
    "DEFAULT_BATCH_DEADLINE_SECONDS",
    "DEFAULT_BATCH_MAX_WORKERS",
    "DEFAULT_TIMEOUT_SECONDS",
    "PYPI_JSON_BASE_URL",
    "ProjectAvailability",
    "fetch_latest_version",
    "probe_availability",
    "probe_availability_many",
]
