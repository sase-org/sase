"""Structural bounds: history work stays constant as selected slot count grows."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.names import rebuild_name_registry
from sase.bead.cli_work_cleanup_apply import prepare_selected_bead_work_force_reuse
from sase.bead.cli_work_cleanup_selection import select_bead_work_launch
from sase.bead.cli_work_cleanup_types import BeadWorkSlot
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


def _seed_history(home: Path, names: tuple[str, ...], *, filler: int) -> None:
    for index in range(filler):
        write_bead_agent_meta(home, f"hist-{index:04d}", done=True)
    for name in names:
        write_bead_agent_meta(home, name, bead_id=name, done=True, outcome="failed")


def _count_full_scans(callback: Callable[[], None]) -> int:
    calls = 0
    real_scan = scan_agent_artifacts

    def tracked_scan(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return real_scan(*args, **kwargs)

    with patch(
        "sase.core.agent_scan_facade.scan_agent_artifacts",
        side_effect=tracked_scan,
    ):
        callback()
    return calls


def test_select_full_scans_do_not_grow_with_slot_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    names = tuple(f"slot-{index}" for index in range(12))
    monkeypatch.setattr(Path, "home", lambda: home)
    _seed_history(home, names, filler=60)
    rebuild_name_registry()
    slots = tuple(_slot(name) for name in names)

    small = _count_full_scans(
        lambda: select_bead_work_launch(slots=slots[:3], bead_assignees={})
    )
    large = _count_full_scans(
        lambda: select_bead_work_launch(slots=slots, bead_assignees={})
    )

    assert small == 1
    assert large == 1


def test_cleanup_apply_full_scans_do_not_grow_with_slot_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    names = tuple(f"slot-{index}" for index in range(12))
    monkeypatch.setattr(Path, "home", lambda: home)
    _seed_history(home, names, filler=60)
    rebuild_name_registry()
    monkeypatch.setattr(
        "sase.bead.cli_work_cleanup_apply.wipe_force_reuse_owners",
        lambda names, **_kwargs: None,
    )

    def apply_k(count: int) -> None:
        selection = select_bead_work_launch(
            slots=tuple(_slot(name) for name in names[:count]),
            bead_assignees={},
        )
        prepare_selected_bead_work_force_reuse(
            _force_reuse_query(names[:count]),
            selection=selection,
            bead_assignees={},
        )

    small = _count_full_scans(lambda: apply_k(3))
    large = _count_full_scans(lambda: apply_k(12))

    assert small == large
    assert small <= 2
