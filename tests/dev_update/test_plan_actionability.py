"""Actionability and missing-source behavior for dev-update planning."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.dev_update.plan import plan_dev_update
import sase.dev_update._plan_roots as plan_mod
from sase.uv_tool.receipt import parse_receipt
from sase.version._git import GitUpstreamStatus
from tests.dev_update._plan_helpers import (
    probe,
    record,
    status,
    stub_fetch_git_upstream,  # noqa: F401 (registers the autouse fixture)
)


@pytest.mark.parametrize(
    ("upstream_status", "reason"),
    [
        (status("/repo", dirty=True), "local changes"),
        (status("/repo", ahead=1, behind=1), "diverged"),
        (
            status("/repo", detached=True, upstream=None, ahead=None, behind=None),
            "detached",
        ),
        (status("/repo", upstream=None, ahead=None, behind=None), "no upstream"),
        (status("/repo", ahead=0, behind=0), "already current"),
    ],
)
def test_plan_dev_update_skips_non_actionable_roots(
    monkeypatch: pytest.MonkeyPatch,
    upstream_status: GitUpstreamStatus,
    reason: str,
) -> None:
    host = record("sase", role="host", source_root="/repo")
    monkeypatch.setattr(
        plan_mod, "classify_git_upstream", lambda _root: upstream_status
    )
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", probe)

    plan = plan_dev_update([host], host_record=host)

    assert plan.actionable == ()
    assert len(plan.skipped) == 1
    assert reason in plan.skipped[0].reason
    assert plan.reconcile_steps == ()


def test_plan_dev_update_unknown_source_root_skips_without_gitprobe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = record("sase", role="host", source_root=None)

    def failprobe(_root: Path) -> GitUpstreamStatus:
        raise AssertionError("missing source roots must not call git")

    monkeypatch.setattr(plan_mod, "classify_git_upstream", failprobe)

    plan = plan_dev_update([host], host_record=host)

    assert len(plan.skipped) == 1
    assert "no source root" in plan.skipped[0].reason


def test_plan_dev_update_receipt_absence_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = record("sase", role="host", source_root="/repo/sase")
    monkeypatch.setattr(
        plan_mod, "classify_git_upstream", lambda _root: status("/repo/sase")
    )
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", probe)

    plan = plan_dev_update([host], host_record=host)

    assert len(plan.reconcile_steps) == 1
    assert plan.reconcile_steps[0].available is False
    assert plan.reconcile_steps[0].reason == "uv tool receipt unavailable"


__all__ = [
    "test_plan_dev_update_receipt_absence_is_explicit",
    "test_plan_dev_update_skips_non_actionable_roots",
    "test_plan_dev_update_unknown_source_root_skips_without_gitprobe",
]
