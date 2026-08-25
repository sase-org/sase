"""Tests for the typed public-PyPI availability probe.

Only a definitive HTTP 404 may report :attr:`ProjectAvailability.MISSING`.
Every other failure mode — timeout, other HTTP errors, malformed payloads —
must report :attr:`ProjectAvailability.UNAVAILABLE` so callers never confuse
an index outage with a definitive absence (see the ``git_fallback`` epic
phase's fallback contract).
"""

from __future__ import annotations

import urllib.error
from typing import Any

from sase.plugins.pypi_source import (
    ProjectAvailability,
    _ProjectProbeResult,
    _probe_project,
    fetch_latest_version,
    probe_availability,
    probe_availability_many,
)


class _Response:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def test__probe_project_available_carries_version() -> None:
    def _urlopen(request: Any, *, timeout: float) -> _Response:
        assert request.full_url == "https://pypi.org/pypi/sase-github/json"
        assert timeout == 2.0
        return _Response(b'{"info": {"version": "0.5.0"}}')

    result = _probe_project("sase-github", urlopen_fn=_urlopen)
    assert result == _ProjectProbeResult(
        status=ProjectAvailability.AVAILABLE, version="0.5.0"
    )


def test__probe_project_404_is_definitively_missing() -> None:
    def _not_found(_request: Any, *, timeout: float) -> _Response:
        raise urllib.error.HTTPError("url", 404, "missing", {}, None)

    result = _probe_project("sase-missing", urlopen_fn=_not_found)
    assert result.status is ProjectAvailability.MISSING
    assert result.version is None


def test__probe_project_other_http_error_is_unavailable_not_missing() -> None:
    def _server_error(_request: Any, *, timeout: float) -> _Response:
        raise urllib.error.HTTPError("url", 503, "unavailable", {}, None)

    result = _probe_project("sase-github", urlopen_fn=_server_error)
    assert result.status is ProjectAvailability.UNAVAILABLE


def test__probe_project_timeout_is_unavailable() -> None:
    def _timeout(_request: Any, *, timeout: float) -> _Response:
        raise TimeoutError("timed out")

    result = _probe_project("sase-github", urlopen_fn=_timeout)
    assert result.status is ProjectAvailability.UNAVAILABLE


def test__probe_project_transport_failure_is_unavailable() -> None:
    def _unreachable(_request: Any, *, timeout: float) -> _Response:
        raise OSError("connection refused")

    result = _probe_project("sase-github", urlopen_fn=_unreachable)
    assert result.status is ProjectAvailability.UNAVAILABLE


def test__probe_project_malformed_payload_is_unavailable() -> None:
    def _bad_json(_request: Any, *, timeout: float) -> _Response:
        return _Response(b"not json")

    def _non_dict(_request: Any, *, timeout: float) -> _Response:
        return _Response(b"[1, 2, 3]")

    def _no_info(_request: Any, *, timeout: float) -> _Response:
        return _Response(b"{}")

    assert _probe_project("x", urlopen_fn=_bad_json).status is (
        ProjectAvailability.UNAVAILABLE
    )
    assert _probe_project("x", urlopen_fn=_non_dict).status is (
        ProjectAvailability.UNAVAILABLE
    )
    assert _probe_project("x", urlopen_fn=_no_info).status is (
        ProjectAvailability.UNAVAILABLE
    )


def test_probe_availability_returns_only_the_status() -> None:
    def _urlopen(_request: Any, *, timeout: float) -> _Response:
        return _Response(b'{"info": {"version": "1.0.0"}}')

    assert probe_availability("sase-github", urlopen_fn=_urlopen) is (
        ProjectAvailability.AVAILABLE
    )


def test_fetch_latest_version_still_delegates_to_the_typed_probe() -> None:
    def _urlopen(_request: Any, *, timeout: float) -> _Response:
        return _Response(b'{"info": {"version": "0.5.0"}}')

    def _not_found(_request: Any, *, timeout: float) -> _Response:
        raise urllib.error.HTTPError("url", 404, "missing", {}, None)

    assert fetch_latest_version("sase-github", urlopen_fn=_urlopen) == "0.5.0"
    assert fetch_latest_version("sase-missing", urlopen_fn=_not_found) is None


def test_probe_availability_many_probes_every_distinct_name() -> None:
    seen: list[str] = []

    def _probe(dist_name: str) -> ProjectAvailability:
        seen.append(dist_name)
        return (
            ProjectAvailability.MISSING
            if dist_name == "sase-missing"
            else ProjectAvailability.AVAILABLE
        )

    result = probe_availability_many(
        ("sase-github", "sase-missing", "sase-github"), probe_fn=_probe
    )
    assert sorted(seen) == ["sase-github", "sase-missing"]
    assert result == {
        "sase-github": ProjectAvailability.AVAILABLE,
        "sase-missing": ProjectAvailability.MISSING,
    }


def test_probe_availability_many_empty_input_makes_no_calls() -> None:
    def _explode(_dist_name: str) -> ProjectAvailability:
        raise AssertionError("must not probe with no names")

    assert probe_availability_many((), probe_fn=_explode) == {}


def test_probe_availability_many_one_failed_probe_does_not_sink_the_batch() -> None:
    def _probe(dist_name: str) -> ProjectAvailability:
        if dist_name == "sase-broken":
            raise RuntimeError("boom")
        return ProjectAvailability.AVAILABLE

    result = probe_availability_many(("sase-github", "sase-broken"), probe_fn=_probe)
    assert result == {
        "sase-github": ProjectAvailability.AVAILABLE,
        "sase-broken": ProjectAvailability.UNAVAILABLE,
    }


def test_probe_availability_many_stops_at_an_already_elapsed_deadline() -> None:
    """N names share one deadline instead of N × the per-probe timeout.

    A zero deadline has already elapsed the instant the batch starts, so the
    loop cancels every pending future before its first wait — deterministic
    regardless of how fast the (never-awaited) worker threads run.
    """
    result = probe_availability_many(
        ("sase-a", "sase-b", "sase-c"),
        probe_fn=lambda _dist_name: ProjectAvailability.AVAILABLE,
        deadline_seconds=0.0,
    )
    assert result == {}
