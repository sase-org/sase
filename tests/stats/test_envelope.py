"""Tests for the versioned ``sase stats`` JSON envelope."""

from __future__ import annotations

from sase.stats.envelope import (
    PROJECT_STATS_SCHEMA,
    STATS_ENVELOPE_SCHEMA_VERSION,
    project_stats_envelope,
)
from tests.stats._project_render_fixtures import one_project_view


def test_envelope_data_is_passthrough() -> None:
    view = one_project_view()
    envelope = project_stats_envelope(view)

    assert envelope["schema"] == PROJECT_STATS_SCHEMA
    assert envelope["schema_version"] == STATS_ENVELOPE_SCHEMA_VERSION
    assert envelope["data"] is view.data
    assert envelope["machine"] == view.machine
    assert envelope["generated_at"] == view.generated_at
    assert envelope["query"]["projects"] == ["gh_sase-org__sase"]
    assert envelope["query"]["group_by"] == "model"
    assert envelope["query"]["range"]["preset"] == "7d"
    assert envelope["query"]["range"]["start_ts"] == view.query.range.start_ts
    assert envelope["query"]["range"]["end_ts"] == view.query.range.end_ts
    assert envelope["query"]["range"]["label"] == "Last 7 days"
    assert envelope["query"]["timezone"] == "America/New_York"
    assert envelope["versions"]["metric_policy"] == 1
    assert envelope["versions"]["sase"]
    assert envelope["versions"]["sase_core"]
    assert set(envelope) == {
        "schema",
        "schema_version",
        "generated_at",
        "machine",
        "query",
        "versions",
        "data",
    }
