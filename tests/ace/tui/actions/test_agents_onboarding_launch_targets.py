"""Tests for Agents onboarding launch-target availability."""

from __future__ import annotations

from dataclasses import dataclass

from sase.ace.tui.actions.agents._onboarding_launch_targets import (
    _launch_targets_available,
)


@dataclass
class _ChangeSpec:
    status: str


def test_launch_targets_available_when_project_present() -> None:
    assert _launch_targets_available(["sase"], []) is True


def test_launch_targets_available_when_eligible_changespec_present() -> None:
    assert _launch_targets_available([], [_ChangeSpec("Draft")]) is True


def test_launch_targets_unavailable_when_empty() -> None:
    assert _launch_targets_available([], []) is False


def test_launch_targets_unavailable_for_home_only() -> None:
    assert _launch_targets_available(["home"], []) is False


def test_launch_targets_unavailable_for_ineligible_changespecs() -> None:
    assert (
        _launch_targets_available(
            [],
            [_ChangeSpec("Submitted"), _ChangeSpec("Reverted")],
        )
        is False
    )


def test_launch_targets_strips_workspace_suffix_from_changespec_status() -> None:
    assert _launch_targets_available([], [_ChangeSpec("Ready (sase_10)")]) is True
