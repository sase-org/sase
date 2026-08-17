"""Regressions for all-or-nothing forced-reuse cleanup (sase-mt)."""

from __future__ import annotations

import pytest

from sase.bead.cli_work_cleanup_apply import prepare_selected_bead_work_force_reuse
from sase.bead.cli_work_cleanup_types import BeadWorkLaunchSelection, CleanupTarget
from sase.bead.cli_work_name_cleanup import ForcedReuseCleanupError


def _target(name: str, *, action: str = "KILL") -> CleanupTarget:
    return CleanupTarget(
        name=name,
        action=action,  # type: ignore[arg-type]
        current_state="active",
        detail="running agent",
        expected_bead_id=name,
        slot_id=name,
    )


def _selection(*targets: CleanupTarget) -> BeadWorkLaunchSelection:
    return BeadWorkLaunchSelection(
        slots=(),
        targets=targets,
        launch_names=frozenset(),
    )


def test_stale_later_target_aborts_before_any_wipe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A TOCTOU failure on target 2 must not have wiped target 1 first."""
    target_a = _target("owner-a")
    target_b = _target("owner-b")
    selection = _selection(target_a, target_b)

    verified: list[str] = []

    def fake_verify(target: CleanupTarget, **_kwargs: object) -> None:
        verified.append(target.name)
        if target.name == "owner-b":
            raise ForcedReuseCleanupError(
                f"bead-work cleanup target {target.name} is no longer "
                "eligible for destructive cleanup"
            )

    wiped: list[str] = []
    monkeypatch.setattr(
        "sase.bead.cli_work_cleanup_apply._verify_cleanup_target_still_selected",
        fake_verify,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_cleanup_apply.wipe_force_reuse_owner",
        lambda name, **_kwargs: wiped.append(name),
    )

    with pytest.raises(ForcedReuseCleanupError, match="owner-b"):
        prepare_selected_bead_work_force_reuse(
            "", selection=selection, bead_assignees={}
        )

    # Both targets were checked before any wipe was attempted, and the
    # verification failure on owner-b left owner-a untouched.
    assert verified == ["owner-a", "owner-b"]
    assert wiped == []


def test_partial_wipe_failure_names_already_wiped_owners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A genuine mid-wipe failure must say what is already gone."""
    target_a = _target("owner-a")
    target_b = _target("owner-b")
    selection = _selection(target_a, target_b)

    monkeypatch.setattr(
        "sase.bead.cli_work_cleanup_apply._verify_cleanup_target_still_selected",
        lambda target, **_kwargs: None,
    )

    def fake_wipe(name: str, **_kwargs: object) -> None:
        if name == "owner-b":
            raise ForcedReuseCleanupError(f"wipe failed for '{name}'")

    monkeypatch.setattr(
        "sase.bead.cli_work_cleanup_apply.wipe_force_reuse_owner",
        fake_wipe,
    )

    with pytest.raises(ForcedReuseCleanupError) as excinfo:
        prepare_selected_bead_work_force_reuse(
            "", selection=selection, bead_assignees={}
        )

    message = str(excinfo.value)
    assert "owner-a" in message
    assert "no live agent" in message


def test_first_target_wipe_failure_has_no_stale_already_wiped_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing was wiped yet, so the error must not claim otherwise."""
    target_a = _target("owner-a")
    selection = _selection(target_a)

    monkeypatch.setattr(
        "sase.bead.cli_work_cleanup_apply._verify_cleanup_target_still_selected",
        lambda target, **_kwargs: None,
    )

    def fake_wipe(name: str, **_kwargs: object) -> None:
        raise ForcedReuseCleanupError(f"wipe failed for '{name}'")

    monkeypatch.setattr(
        "sase.bead.cli_work_cleanup_apply.wipe_force_reuse_owner",
        fake_wipe,
    )

    with pytest.raises(ForcedReuseCleanupError) as excinfo:
        prepare_selected_bead_work_force_reuse(
            "", selection=selection, bead_assignees={}
        )

    assert str(excinfo.value) == "wipe failed for 'owner-a'"
