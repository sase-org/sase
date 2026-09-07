"""Targeted cleanup verification must not rescan whole-agent history."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.names import claim_registered_name, rebuild_name_registry
from sase.bead.cli_work_cleanup_apply import prepare_selected_bead_work_force_reuse
from sase.bead.cli_work_cleanup_selection import select_bead_work_launch
from sase.bead.cli_work_cleanup_types import (
    BeadWorkLaunchSelection,
    BeadWorkSlot,
    CleanupTarget,
)
from sase.bead.cli_work_name_cleanup import ForcedReuseCleanupError
from sase.core.agent_scan_facade import scan_agent_artifacts

from .cli_work_helpers import write_bead_agent_meta


def _slot(name: str) -> BeadWorkSlot:
    return BeadWorkSlot(
        slot_id=name,
        owner_name=name,
        expected_bead_id=name,
        launch_name=name,
    )


def _force_reuse_query(names: tuple[str, ...]) -> str:
    return "\n---\n".join(f"%id(!{name})" for name in names)


def _seed_done_owners(home: Path, names: tuple[str, ...], *, filler: int) -> None:
    for index in range(filler):
        write_bead_agent_meta(home, f"hist-{index:04d}", done=True)
    for name in names:
        write_bead_agent_meta(home, name, bead_id=name, done=True, outcome="failed")


def test_cleanup_verify_does_not_rescan_history_per_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    names = tuple(f"owner-{index}" for index in range(8))
    monkeypatch.setattr(Path, "home", lambda: home)
    _seed_done_owners(home, names, filler=40)
    rebuild_name_registry()
    selection = select_bead_work_launch(
        slots=tuple(_slot(name) for name in names),
        bead_assignees={},
    )
    assert len(selection.destructive_targets) == 8

    scan_calls = 0
    real_scan = scan_agent_artifacts

    def tracked_scan(*args: object, **kwargs: object) -> object:
        nonlocal scan_calls
        scan_calls += 1
        return real_scan(*args, **kwargs)

    monkeypatch.setattr(
        "sase.bead.cli_work_cleanup_apply.wipe_force_reuse_owners",
        lambda names, **_kwargs: None,
    )
    with patch(
        "sase.core.agent_scan_facade.scan_agent_artifacts",
        side_effect=tracked_scan,
    ):
        prepare_selected_bead_work_force_reuse(
            _force_reuse_query(names),
            selection=selection,
            bead_assignees={},
        )

    assert scan_calls == 0


def test_cleanup_verify_aborts_when_target_state_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    name = "owner-a"
    monkeypatch.setattr(Path, "home", lambda: home)
    artifact = write_bead_agent_meta(
        home, name, bead_id=name, done=True, outcome="failed"
    )
    rebuild_name_registry()
    selection = select_bead_work_launch(slots=(_slot(name),), bead_assignees={})
    assert selection.destructive_targets
    (artifact / "done.json").unlink()
    (artifact / "waiting.json").write_text(
        '{"waiting_for": ["upstream"]}', encoding="utf-8"
    )

    monkeypatch.setattr(
        "sase.bead.cli_work_cleanup_apply.wipe_force_reuse_owners",
        lambda names, **_kwargs: pytest.fail("changed target must not be wiped"),
    )
    with pytest.raises(
        ForcedReuseCleanupError,
        match="changed before wipe|no longer eligible",
    ):
        prepare_selected_bead_work_force_reuse(
            _force_reuse_query((name,)),
            selection=selection,
            bead_assignees={},
        )


def test_cleanup_verify_aborts_when_selected_artifact_disappears(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    name = "owner-missing"
    monkeypatch.setattr(Path, "home", lambda: home)
    artifact = write_bead_agent_meta(
        home, name, bead_id=name, done=True, outcome="failed"
    )
    rebuild_name_registry()
    selection = select_bead_work_launch(slots=(_slot(name),), bead_assignees={})
    for child in artifact.iterdir():
        child.unlink()
    artifact.rmdir()

    monkeypatch.setattr(
        "sase.bead.cli_work_cleanup_apply.wipe_force_reuse_owners",
        lambda names, **_kwargs: pytest.fail("missing target must not be wiped"),
    )
    with pytest.raises(ForcedReuseCleanupError, match="no longer eligible"):
        prepare_selected_bead_work_force_reuse(
            _force_reuse_query((name,)),
            selection=selection,
            bead_assignees={},
        )


def test_cleanup_verify_wipes_failed_owner_with_dead_retry_assignee(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    owner = "sase-x7.4"
    dead_retry = "sase-x7.4.r0.r0"
    monkeypatch.setattr(Path, "home", lambda: home)
    write_bead_agent_meta(home, owner, bead_id=owner, done=True, outcome="failed")
    write_bead_agent_meta(home, dead_retry, bead_id=owner, done=True)
    rebuild_name_registry()
    assignees = {owner: dead_retry}
    selection = select_bead_work_launch(
        slots=(_slot(owner),),
        bead_assignees=assignees,
    )
    assert selection.destructive_targets

    wiped: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        "sase.bead.cli_work_cleanup_apply.wipe_force_reuse_owners",
        lambda names, **_kwargs: wiped.append(tuple(names)),
    )
    prepare_selected_bead_work_force_reuse(
        _force_reuse_query((owner,)),
        selection=selection,
        bead_assignees=assignees,
    )

    assert wiped == [(owner,)]


def test_cleanup_verify_aborts_when_retry_descendant_goes_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    owner = "sase-x7.4"
    live_retry = "sase-x7.4.r0"
    monkeypatch.setattr(Path, "home", lambda: home)
    write_bead_agent_meta(home, owner, bead_id=owner, done=True, outcome="failed")
    rebuild_name_registry()
    assignees = {owner: live_retry}
    selection = select_bead_work_launch(
        slots=(_slot(owner),),
        bead_assignees=assignees,
    )
    assert selection.destructive_targets

    descendant = write_bead_agent_meta(home, live_retry, bead_id=owner)
    claim_registered_name(live_retry, descendant, replace_existing=True)
    monkeypatch.setattr(
        "sase.bead.cli_work_cleanup_apply.wipe_force_reuse_owners",
        lambda names, **_kwargs: pytest.fail("live retry descendant must not be wiped"),
    )
    with pytest.raises(ForcedReuseCleanupError, match="no longer eligible"):
        prepare_selected_bead_work_force_reuse(
            _force_reuse_query((owner,)),
            selection=selection,
            bead_assignees=assignees,
        )


def test_cleanup_verify_classifies_stale_registry_owner_with_dead_descendant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.names._registry_store import (
        registry_data,
        registry_path,
        write_registry,
    )
    from sase.bead.cli_work_cleanup_targets import classify_stale_registry_owner

    home = tmp_path / "home"
    owner = "sase-x7.4"
    dead_retry = "sase-x7.4.r0.r0"
    monkeypatch.setattr(Path, "home", lambda: home)
    write_bead_agent_meta(home, dead_retry, bead_id=owner, done=True)
    write_registry(
        registry_path(),
        registry_data(
            {
                owner: {
                    "name": owner,
                    "source": "artifact",
                    "state": "done",
                }
            }
        ),
    )
    selection = BeadWorkLaunchSelection(
        slots=(_slot(owner),),
        targets=(
            CleanupTarget(
                name=owner,
                action="REMOVE",
                current_state="completed",
                detail=f"stored owner for bead {owner}",
                expected_bead_id=owner,
                slot_id=owner,
            ),
        ),
        launch_names=frozenset({owner}),
    )
    stale_calls = 0
    real_stale = classify_stale_registry_owner

    def tracked_stale(*args: object, **kwargs: object) -> object:
        nonlocal stale_calls
        stale_calls += 1
        return real_stale(*args, **kwargs)

    monkeypatch.setattr(
        "sase.bead.cli_work_cleanup_targets.classify_stale_registry_owner",
        tracked_stale,
    )
    wiped: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        "sase.bead.cli_work_cleanup_apply.wipe_force_reuse_owners",
        lambda names, **_kwargs: wiped.append(tuple(names)),
    )
    prepare_selected_bead_work_force_reuse(
        _force_reuse_query((owner,)),
        selection=selection,
        bead_assignees={owner: dead_retry},
    )

    assert stale_calls == 1
    assert wiped == [(owner,)]
