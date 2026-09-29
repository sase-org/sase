"""Summary-wiring tests for agent bead touches.

Split from ``test_agent_bead_touches``; shared builders live in
``_agent_bead_touches_helpers`` and the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

import pytest

from sase.ace.tui._bead_touches_shared import BeadTouchDisplayEvent
from sase.ace.tui.artifact_reads import ArtifactReadDisplayEvent
from sase.ace.tui.bead_touches import BeadTouchEntry
from tests.ace.tui.widgets._agent_bead_touches_helpers import (
    make_bead_read,
    make_bead_touch,
    make_bead_touch_display,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent

__all__ = [
    "test_artifacts_lane_empty_index_resolves_empty_view",
    "test_artifacts_lane_resolves_merged_bead_touch_entries",
    "test_cache_merge_keeps_bead_view_when_other_lane_rebuilds",
    "test_non_artifacts_lane_leaves_bead_view_unresolved",
]


def _stub_artifacts_resolvers(
    monkeypatch: pytest.MonkeyPatch,
    *,
    reads: tuple[ArtifactReadDisplayEvent, ...] = (),
    touches: tuple[BeadTouchDisplayEvent, ...] = (),
) -> None:
    """Keep the artifacts-lane resolvers cheap and deterministic."""
    from sase.ace.tui.models.agent_associated_plan import _AgentPlanEnrichment
    from sase.ace.tui.widgets.prompt_panel import _agent_display_header_summary

    monkeypatch.setattr(
        _agent_display_header_summary,
        "resolve_agent_plan_enrichment",
        lambda agent: _AgentPlanEnrichment("ordinary", None, None, ()),
    )
    monkeypatch.setattr(
        "sase.ace.tui.artifact_reads.load_artifact_reads_for_agent_context",
        lambda agent: reads,
    )
    monkeypatch.setattr(
        "sase.ace.tui.bead_touches.load_bead_touches_for_agent_context",
        lambda agent: touches,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._artifact_files.artifact_file_paths",
        lambda agent: [],
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.file_panel._linked_deltas.get_cached_linked_delta_groups",
        lambda agent: (),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_deltas."
        "agent_commit_linked_delta_groups",
        lambda agent: (),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_deltas.agent_delta_entries",
        lambda agent: [],
    )


def _wiring_agent() -> object:
    return make_agent(
        agent_name="worker",
        cl_name="worker_cl",
        phase_bead_id="sase-14j.4",
        epic_bead_id="sase-14j",
    )


def test_artifacts_lane_resolves_merged_bead_touch_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.widgets.prompt_panel._agent_display_header_summary import (
        build_detail_header_summary,
    )

    touch = make_bead_touch(
        "worker",
        "sase-14j.4",
        verbs={"noted": 2},
        title="Resolve touches",
        last_at="2026-09-20T16:00:00Z",
    )
    _stub_artifacts_resolvers(
        monkeypatch,
        touches=(make_bead_touch_display(touch),),
        reads=(
            make_bead_read("bead:sase-14j.4", "2026-09-20T16:05:00Z", read_id="r1"),
            make_bead_read(
                "plan:202608/design.md", "2026-09-20T16:06:00Z", read_id="r2"
            ),
        ),
    )

    summary = build_detail_header_summary(
        _wiring_agent(),
        lanes=frozenset({"artifacts"}),  # type: ignore[arg-type]
    )

    assert summary.ready_lanes == frozenset({"artifacts"})
    assert [entry.bead_id for entry in summary.bead_touch_entries] == [
        "sase-14j.4",
        "sase-14j",
    ]
    worked = summary.bead_touch_entries[0]
    assert worked.verbs == {"noted": 2, "read": 1}
    assert worked.title == "Resolve touches"
    assert worked.own is True
    assert worked.last_at == "2026-09-20T16:05:00Z"
    untouched = summary.bead_touch_entries[1]
    assert untouched.own is True
    assert untouched.verbs == {}
    # The non-bead read stays out of the bead view.
    assert len(summary.bead_touch_entries) == 2


def test_artifacts_lane_empty_index_resolves_empty_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.widgets.prompt_panel._agent_display_header_summary import (
        build_detail_header_summary,
    )

    _stub_artifacts_resolvers(monkeypatch)

    summary = build_detail_header_summary(
        _wiring_agent(),
        lanes=frozenset({"artifacts"}),  # type: ignore[arg-type]
    )

    # The assigned-but-untouched beads still appear as own rows. Both
    # are timestamp-less, so the bead-id tiebreak orders them.
    assert [entry.bead_id for entry in summary.bead_touch_entries] == [
        "sase-14j",
        "sase-14j.4",
    ]
    assert all(entry.verbs == {} for entry in summary.bead_touch_entries)


def test_non_artifacts_lane_leaves_bead_view_unresolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.widgets.prompt_panel._agent_display_header_summary import (
        build_detail_header_summary,
    )

    _stub_artifacts_resolvers(monkeypatch)

    summary = build_detail_header_summary(
        _wiring_agent(),
        lanes=frozenset({"skills"}),  # type: ignore[arg-type]
    )

    assert summary.bead_touch_entries == ()
    assert "artifacts" not in summary.ready_lanes


def test_cache_merge_keeps_bead_view_when_other_lane_rebuilds() -> None:
    from sase.ace.tui.widgets.prompt_panel._agent_display_header_summary import (
        cache_detail_header_summary,
        get_cached_detail_header_summary,
    )
    from sase.ace.tui.widgets.prompt_panel._agent_display_state import (
        DetailHeaderSummary,
    )

    class _Widget:
        """A bare panel stand-in; the cache lives on an arbitrary attribute."""

    widget = _Widget()
    agent = make_agent()
    view = (BeadTouchEntry(bead_id="sase-14j.4", own=True),)
    cache_detail_header_summary(
        widget,
        agent,  # type: ignore[arg-type]
        DetailHeaderSummary(
            artifact_reads=(),
            bead_touch_entries=view,
        ),
    )

    cache_detail_header_summary(
        widget,
        agent,  # type: ignore[arg-type]
        DetailHeaderSummary(
            skill_uses=(),
            ready_lanes=frozenset({"skills"}),
        ),
    )

    merged = get_cached_detail_header_summary(widget, agent)  # type: ignore[arg-type]
    assert merged is not None
    assert merged.bead_touch_entries == view
