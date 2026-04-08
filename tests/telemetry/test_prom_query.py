"""Tests for ``sase.telemetry.prom_query`` — Prometheus API client."""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import patch

from sase.telemetry.prom_query import (
    TimeSeries,
    check_prometheus_reachable,
    query_range,
)

# ── Helpers ──────────────────────────────────────────────────────────


def _mock_response(body: dict, status: int = 200) -> object:
    """Create a mock HTTP response object."""
    data = json.dumps(body).encode()
    resp = BytesIO(data)
    resp.status = status  # type: ignore[attr-defined]
    resp.__enter__ = lambda s: s  # type: ignore[attr-defined]
    resp.__exit__ = lambda s, *a: None  # type: ignore[attr-defined]
    return resp


# ── check_prometheus_reachable ───────────────────────────────────────


def test_reachable_returns_true() -> None:
    resp = BytesIO(b"OK")
    resp.status = 200  # type: ignore[attr-defined]
    resp.__enter__ = lambda s: s  # type: ignore[attr-defined]
    resp.__exit__ = lambda s, *a: None  # type: ignore[attr-defined]

    with patch("sase.telemetry.prom_query.urllib.request.urlopen", return_value=resp):
        assert check_prometheus_reachable("http://localhost:9090") is True


def test_reachable_returns_false_on_error() -> None:
    with patch(
        "sase.telemetry.prom_query.urllib.request.urlopen",
        side_effect=OSError("connection refused"),
    ):
        assert check_prometheus_reachable("http://localhost:9090") is False


# ── query_range ──────────────────────────────────────────────────────


def test_query_range_parses_matrix() -> None:
    body = {
        "status": "success",
        "data": {
            "resultType": "matrix",
            "result": [
                {
                    "metric": {"__name__": "sase_agent_active", "project": "sase"},
                    "values": [[1000, "2"], [1015, "3"], [1030, "5"]],
                }
            ],
        },
    }
    with patch(
        "sase.telemetry.prom_query.urllib.request.urlopen",
        return_value=_mock_response(body),
    ):
        result = query_range("http://localhost:9090", "sase_agent_active", 1000, 1030)

    assert len(result) == 1
    ts = result[0]
    assert ts.metric == "sase_agent_active"
    assert ts.labels == {"project": "sase"}
    assert len(ts.points) == 3
    assert ts.points[0] == (1000.0, 2.0)
    assert ts.points[2] == (1030.0, 5.0)


def test_query_range_returns_empty_on_network_error() -> None:
    with patch(
        "sase.telemetry.prom_query.urllib.request.urlopen",
        side_effect=OSError("timeout"),
    ):
        result = query_range("http://localhost:9090", "up", 0, 100)
    assert result == []


def test_query_range_returns_empty_on_non_success() -> None:
    body = {"status": "error", "errorType": "bad_data", "error": "parse error"}
    with patch(
        "sase.telemetry.prom_query.urllib.request.urlopen",
        return_value=_mock_response(body),
    ):
        result = query_range("http://localhost:9090", "bad{", 0, 100)
    assert result == []


def test_query_range_multi_series() -> None:
    body = {
        "status": "success",
        "data": {
            "resultType": "matrix",
            "result": [
                {
                    "metric": {"__name__": "up", "instance": "a"},
                    "values": [[100, "1"]],
                },
                {
                    "metric": {"__name__": "up", "instance": "b"},
                    "values": [[100, "0"]],
                },
            ],
        },
    }
    with patch(
        "sase.telemetry.prom_query.urllib.request.urlopen",
        return_value=_mock_response(body),
    ):
        result = query_range("http://localhost:9090", "up", 100, 100)
    assert len(result) == 2
    assert result[0].labels["instance"] == "a"
    assert result[1].labels["instance"] == "b"


# ── Edge cases ───────────────────────────────────────────────────────


def test_query_range_empty_values() -> None:
    body = {
        "status": "success",
        "data": {
            "resultType": "matrix",
            "result": [
                {
                    "metric": {"__name__": "sase_agent_active"},
                    "values": [],
                }
            ],
        },
    }
    with patch(
        "sase.telemetry.prom_query.urllib.request.urlopen",
        return_value=_mock_response(body),
    ):
        result = query_range("http://localhost:9090", "sase_agent_active", 0, 100)

    assert len(result) == 1
    assert result[0].points == []


def test_query_range_empty_result_list() -> None:
    body = {"status": "success", "data": {"resultType": "matrix", "result": []}}
    with patch(
        "sase.telemetry.prom_query.urllib.request.urlopen",
        return_value=_mock_response(body),
    ):
        result = query_range("http://localhost:9090", "nonexistent", 0, 100)
    assert result == []


# ── TimeSeries dataclass ─────────────────────────────────────────────


def test_timeseries_defaults() -> None:
    ts = TimeSeries(metric="test")
    assert ts.metric == "test"
    assert ts.labels == {}
    assert ts.points == []
