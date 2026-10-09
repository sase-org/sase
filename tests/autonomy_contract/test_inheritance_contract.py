"""Inheritance contract: host-composed successors keep the live ``%auto`` state.

E1 target: every host-composed successor inherits its predecessor's live
record structurally. Today ``create_followup_artifacts`` copies only the
``approve`` key, so ``:tale``/``:epic`` arguments are lost and monitor
follow-ups re-emit a widened or stale prefix. Each test below fails for
that documented reason; the ``inherit`` phase removes these markers.
"""

from __future__ import annotations

import pytest

from . import harness

pytestmark = pytest.mark.xfail(
    strict=True, reason="E1 inherit: successors inherit the live record"
)


def test_tale_successor_keeps_tale_keys(tmp_path) -> None:
    """A ``%auto:tale`` successor keeps the tale argument and action."""
    workdir = tmp_path / "work"
    workdir.mkdir()
    _, live_meta, predecessor = harness.launch_meta("%auto:tale\nDo the work", workdir)

    successor_meta = harness.adapt_followup_artifacts(
        live_meta, tmp_path, suffix="--pipe"
    )

    assert successor_meta.get("auto_approve_argument") == "tale"
    assert successor_meta.get("auto_approve_plan_action") == "tale"


def test_tale_monitor_followup_keeps_tale(tmp_path) -> None:
    """A monitor follow-up of a ``%auto:tale`` agent re-emits ``:tale``."""
    workdir = tmp_path / "work"
    workdir.mkdir()
    _, live_meta, _ = harness.launch_meta("%auto:tale\nDo the work", workdir)
    member_meta = harness.adapt_followup_artifacts(
        live_meta, tmp_path, suffix="--monitor"
    )

    assert harness.adapt_monitor_followup_prefix(member_meta) == "%auto:tale\n"


def test_plan_monitor_followup_not_widened(tmp_path) -> None:
    """A monitor follow-up of ``%auto:plan`` is not widened to bare."""
    workdir = tmp_path / "work"
    workdir.mkdir()
    _, live_meta, _ = harness.launch_meta("%auto:plan\nDo the work", workdir)
    member_meta = harness.adapt_followup_artifacts(
        live_meta, tmp_path, suffix="--monitor"
    )

    assert harness.adapt_monitor_followup_prefix(member_meta) == "%auto:plan\n"


def test_a_off_monitor_followup_parks(tmp_path) -> None:
    """``A`` off on the live member means the next follow-up is manual."""
    workdir = tmp_path / "work"
    workdir.mkdir()
    _, live_meta, predecessor = harness.launch_meta("%auto\nDo the work", workdir)
    member_meta = harness.adapt_followup_artifacts(
        live_meta, tmp_path, suffix="--monitor"
    )
    harness.adapt_a_off(predecessor)

    assert harness.adapt_monitor_followup_prefix(member_meta) == ""
