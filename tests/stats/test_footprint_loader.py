"""Footprint report loading through the shared Statistics view loader."""

from __future__ import annotations

from datetime import datetime, timezone, UTC

from sase.stats import loader
from sase.stats.ranges import StatsRange


def test_footprint_loader_uses_day_window_actor_lens_and_area(monkeypatch) -> None:
    import sase.footprint.query as footprint_query

    requests: list[dict[str, object]] = []

    def build_request(**kwargs: object) -> dict[str, object]:
        request = dict(kwargs)
        requests.append(request)
        return request

    monkeypatch.setattr(loader, "get_timezone", lambda: UTC)
    monkeypatch.setattr(footprint_query, "build_report_request", build_request)
    monkeypatch.setattr(
        footprint_query,
        "fetch_report",
        lambda request: {"request": dict(request)},
    )
    selected_range = StatsRange(
        int(datetime(2026, 10, 1, tzinfo=UTC).timestamp()),
        int(datetime(2026, 10, 31, tzinfo=UTC).timestamp()),
        "October",
        "October",
    )

    result = loader.load_statistics_view(
        "footprint",
        selected_range,
        "sase",
        footprint_lens="cold",
        footprint_actor="agents",
        footprint_area="cli.bead",
    )

    assert requests == [
        {
            "lens": "cold",
            "actor": "agents",
            "window_days": 30,
            "area": "cli.bead",
            "today": "2026-10-30",
        }
    ]
    assert result.view == "footprint"
    assert result.project_filter == "sase"
    assert result.footprint_lens == "cold"
    assert result.footprint_actor == "agents"
    assert result.footprint_area == "cli.bead"
    assert result.footprint == {"request": requests[0]}


def test_footprint_loader_keeps_all_time_window_open(monkeypatch) -> None:
    import sase.footprint.query as footprint_query

    requests: list[dict[str, object]] = []
    monkeypatch.setattr(loader, "get_timezone", lambda: UTC)
    monkeypatch.setattr(
        footprint_query,
        "build_report_request",
        lambda **kwargs: requests.append(dict(kwargs)) or dict(kwargs),
    )
    monkeypatch.setattr(footprint_query, "fetch_report", lambda request: dict(request))

    result = loader.load_statistics_view(
        "footprint",
        StatsRange(0, 1_800_000_000, "all", "All time"),
    )

    assert requests[0]["window_days"] is None
    assert result.footprint == requests[0]
