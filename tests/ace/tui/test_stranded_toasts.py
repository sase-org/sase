"""Incident-keyed stranded toasts with burst coalescing."""

from __future__ import annotations

from sase.ace.tui.models import _agent_stranded_cache as stranded_cache

import pytest

from sase.ace.tui.actions.agents import _stranded_toasts
from sase.ace.tui.models import agent_stranded
from sase.bead.stranded import StrandedReport
from sase.core.stranded_work_facade import StrandedWorkReport, StrandedWorkVerdict


@pytest.fixture(autouse=True)
def _clear_stranded_state():
    stranded_cache._STRANDED_REPORT_CACHE.clear()
    _stranded_toasts._SEEN_LEAVES.clear()
    yield
    stranded_cache._STRANDED_REPORT_CACHE.clear()
    _stranded_toasts._SEEN_LEAVES.clear()


def _verdict(
    bead_id: str,
    state: str = "stranded",
    **fields: object,
) -> StrandedWorkVerdict:
    if state == "stranded":
        reason = fields.pop("reason", "kept")
    else:
        reason = fields.pop("reason", None)
    return StrandedWorkVerdict(
        bead_id=bead_id,
        kind="phase",
        state=state,
        reason=reason,  # type: ignore[arg-type]
        since=1.0,
        **fields,  # type: ignore[arg-type]
    )


def _set_report(
    *verdicts: StrandedWorkVerdict,
    records_unavailable: int = 0,
) -> None:
    report = StrandedWorkReport(
        verdicts=verdicts,
        stranded_ids=tuple(v.bead_id for v in verdicts if v.state == "stranded"),
        blocked_ids=tuple(v.bead_id for v in verdicts if v.state == "blocked"),
    )
    stranded_cache._STRANDED_REPORT_CACHE.set(
        "demo",
        StrandedReport(
            report=report,
            titles={},
            generated_at=3601.0,
            records_unavailable=records_unavailable,
        ),
        "test",
    )


def _stranded(
    bead_id: str,
    *,
    artifact_dir: str = "/tmp/turn-1",
    last_turn: str | None = None,
    session: str | None = None,
) -> StrandedWorkVerdict:
    return _verdict(
        bead_id,
        "stranded",
        last_turn_artifact_dir=artifact_dir,
        last_turn=last_turn or f"{bead_id}--3",
        session=session or bead_id,
    )


def test_degraded_flap_back_to_same_incident_is_silent() -> None:
    _set_report(_stranded("sase-demo.1"))
    assert _stranded_toasts.announce_stranded_transitions([], ("demo",)) == []

    _set_report(
        _verdict("sase-demo.1", "unknown", reason="records_unavailable"),
        records_unavailable=1,
    )
    assert _stranded_toasts.announce_stranded_transitions([], ("demo",)) == []

    _set_report(_stranded("sase-demo.1"))
    assert _stranded_toasts.announce_stranded_transitions([], ("demo",)) == []


def test_absence_flap_back_to_same_incident_is_silent() -> None:
    _set_report(_stranded("sase-demo.1"))
    assert _stranded_toasts.announce_stranded_transitions([], ("demo",)) == []

    _set_report()
    assert _stranded_toasts.announce_stranded_transitions([], ("demo",)) == []

    _set_report(_stranded("sase-demo.1"))
    assert _stranded_toasts.announce_stranded_transitions([], ("demo",)) == []


def test_same_bead_with_new_incident_toasts_once() -> None:
    _set_report(_stranded("sase-demo.1", artifact_dir="/tmp/turn-1"))
    assert _stranded_toasts.announce_stranded_transitions([], ("demo",)) == []

    _set_report(_stranded("sase-demo.1", artifact_dir="/tmp/turn-2"))
    messages = _stranded_toasts.announce_stranded_transitions([], ("demo",))
    assert len(messages) == 1
    assert messages[0].startswith("⚐ sase-demo.1 is stranded:")


def test_degraded_first_report_sets_no_baseline() -> None:
    _set_report(
        _verdict("sase-demo.1", "unknown", reason="records_unavailable"),
        records_unavailable=1,
    )
    assert _stranded_toasts.announce_stranded_transitions([], ("demo",)) == []
    assert "demo" not in _stranded_toasts._SEEN_LEAVES

    _set_report(_stranded("sase-demo.1"))
    assert _stranded_toasts.announce_stranded_transitions([], ("demo",)) == []


def test_three_new_leaves_emit_three_messages() -> None:
    _set_report()
    assert _stranded_toasts.announce_stranded_transitions([], ("demo",)) == []

    _set_report(
        _stranded("sase-demo.1"),
        _stranded("sase-demo.2"),
        _stranded("sase-demo.3"),
    )
    messages = _stranded_toasts.announce_stranded_transitions([], ("demo",))
    assert len(messages) == 3


def test_five_new_leaves_collapse_to_one_summary() -> None:
    _set_report()
    assert _stranded_toasts.announce_stranded_transitions([], ("demo",)) == []

    _set_report(
        _stranded("sase-demo.1"),
        _stranded("sase-demo.2"),
        _stranded("sase-demo.3"),
        _stranded("sase-demo.4"),
        _stranded("sase-demo.5"),
    )
    messages = _stranded_toasts.announce_stranded_transitions([], ("demo",))
    assert messages == [
        "⚐ 5 beads newly stranded: sase-demo.1, sase-demo.2, sase-demo.3 (+2 more)."
    ]
