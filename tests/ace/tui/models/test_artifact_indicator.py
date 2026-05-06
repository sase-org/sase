from __future__ import annotations

from typing import cast

from rich.text import Text

from sase.ace.tui.models.artifact_indicator import (
    ArtifactIndicator,
    ArtifactIndicatorState,
    artifact_indicator_from_summary,
    artifact_indicator_width,
    render_artifact_indicator,
)
from sase.core.artifact_wire import ArtifactSummaryWire, ArtifactTypeCountWire


def _count(artifact_type: str, total_count: int) -> ArtifactTypeCountWire:
    return ArtifactTypeCountWire(
        artifact_type=artifact_type,
        total_count=total_count,
    )


def _summary(
    *,
    state: str = "ok",
    total_linked_count: int = 0,
    file_type_counts: list[ArtifactTypeCountWire] | None = None,
    kind_counts: list[ArtifactTypeCountWire] | None = None,
    error: str | None = None,
) -> ArtifactSummaryWire:
    return ArtifactSummaryWire(
        artifact_id="cl-1",
        state=state,
        total_linked_count=total_linked_count,
        file_type_counts=file_type_counts or [],
        kind_counts=kind_counts or [],
        error=error,
    )


def _style_spans(text: Text) -> list[tuple[int, int, str]]:
    return [(span.start, span.end, str(span.style)) for span in text.spans]


def test_artifact_indicator_orders_counts_and_suppresses_zeroes() -> None:
    indicator = artifact_indicator_from_summary(
        _summary(
            total_linked_count=13,
            file_type_counts=[
                _count("misc", 2),
                _count("chat", 3),
                _count("prompt", 0),
                _count("diff", 1),
                _count("plan", 2),
            ],
            kind_counts=[
                _count("zeta", 1),
                _count("commit", 1),
                _count("agent", 2),
                _count("bead", 0),
                _count("changespec", 1),
                _count("alpha", 1),
            ],
        )
    )

    rendered = render_artifact_indicator(indicator)

    assert (
        rendered.plain
        == "art 13 plan2 diff1 chat3 misc2 agent2 commit1 changespec1 alpha1 zeta1"
    )


def test_artifact_indicator_aggregates_duplicate_counts() -> None:
    indicator = artifact_indicator_from_summary(
        _summary(
            total_linked_count=4,
            file_type_counts=[_count("diff", 1), _count("diff", 2)],
            kind_counts=[_count("agent", 1), _count("agent", 3)],
        )
    )

    assert render_artifact_indicator(indicator).plain == "art 4 diff3 agent4"


def test_artifact_indicator_renders_empty_for_zero_ok_summary() -> None:
    indicator = artifact_indicator_from_summary(_summary(total_linked_count=0))

    assert render_artifact_indicator(indicator).plain == ""
    assert artifact_indicator_width(indicator) == 0


def test_artifact_indicator_renders_unavailable_states() -> None:
    for state in ("missing", "loading", "stale"):
        indicator = ArtifactIndicator(
            artifact_id="cl-1",
            state=cast(ArtifactIndicatorState, state),
        )

        rendered = render_artifact_indicator(indicator)

        assert rendered.plain == "art ?"
        assert str(rendered.style) == "dim"


def test_artifact_indicator_renders_error_state() -> None:
    indicator = artifact_indicator_from_summary(
        _summary(state="error", error="index unavailable")
    )

    rendered = render_artifact_indicator(indicator)

    assert rendered.plain == "art !"
    assert "dim" in str(rendered.style)


def test_artifact_indicator_placeholder_helper_does_not_require_summary() -> None:
    assert artifact_indicator_from_summary(None) is None
    assert (
        render_artifact_indicator(
            artifact_indicator_from_summary(None, "cl-1", loading=True)
        ).plain
        == "art ?"
    )
    assert (
        render_artifact_indicator(
            artifact_indicator_from_summary(None, "cl-1", error="backend")
        ).plain
        == "art !"
    )


def test_artifact_indicator_width_is_deterministic() -> None:
    indicator = artifact_indicator_from_summary(
        _summary(
            total_linked_count=3,
            file_type_counts=[_count("plan", 2), _count("diff", 1)],
        )
    )

    rendered = render_artifact_indicator(indicator)

    assert (
        artifact_indicator_width(indicator) == rendered.cell_len == len(rendered.plain)
    )


def test_artifact_indicator_output_is_identical_for_cl_and_agent_callers() -> None:
    indicator = artifact_indicator_from_summary(
        _summary(
            total_linked_count=2,
            file_type_counts=[_count("chat", 1)],
            kind_counts=[_count("agent", 1)],
        )
    )

    cl_text = render_artifact_indicator(indicator)
    agent_text = render_artifact_indicator(indicator)

    assert cl_text.plain == agent_text.plain == "art 2 chat1 agent1"
    assert _style_spans(cl_text) == _style_spans(agent_text)
