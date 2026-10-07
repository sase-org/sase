"""Target selection and hint flow tests for the sidecar auto-sync chop."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import sase.scripts.sase_chop_sidecar_auto_sync as sidecar_sync_chop
from sase._sidecar_auto_sync import SidecarSyncResult
from tests._axe_chop_sidecar_auto_sync_support import (
    configure_sidecar_sync,
    make_project,
    make_runtime,
)


def test_no_auto_sync_roles_short_circuits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_sidecar_sync(
        monkeypatch,
        tmp_path,
        records=[make_project(tmp_path)],
        roles_by_project={},
    )

    result = sidecar_sync_chop._run(make_runtime(tmp_path))

    assert result.reason == "no_auto_sync_roles"
    assert result.counters["targets"] == 0


def test_hinted_role_refreshes_and_clears_its_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_sidecar_sync(
        monkeypatch,
        tmp_path,
        records=[make_project(tmp_path)],
        roles_by_project={"proj": ("plans",)},
        hinted_by_project={"proj": ("plans",)},
    )
    sync = MagicMock(
        return_value=SidecarSyncResult("proj", "plans", "refreshed", "fast-forwarded")
    )
    monkeypatch.setattr(sidecar_sync_chop, "sync_primary_sidecar_role", sync)
    clear = MagicMock()
    monkeypatch.setattr(sidecar_sync_chop, "clear_sidecar_sync_hint", clear)

    result = sidecar_sync_chop._run(make_runtime(tmp_path))

    sync.assert_called_once()
    args, kwargs = sync.call_args
    assert args[0] == "proj"
    assert args[1] == "plans"
    clear.assert_called_once_with("proj", "plans")
    assert result.status == "ok"
    assert result.counters["refreshed"] == 1


def test_multiple_roles_in_one_project_are_all_attempted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_sidecar_sync(
        monkeypatch,
        tmp_path,
        records=[make_project(tmp_path)],
        roles_by_project={"proj": ("plans", "beads", "research", "custom_docs")},
    )
    seen: list[str] = []

    def sync(project: str, role: str, **_kwargs: object) -> SidecarSyncResult:
        seen.append(role)
        return SidecarSyncResult(project, role, "up_to_date", "already fresh")

    monkeypatch.setattr(sidecar_sync_chop, "sync_primary_sidecar_role", sync)

    result = sidecar_sync_chop._run(make_runtime(tmp_path))

    assert sorted(seen) == ["beads", "custom_docs", "plans", "research"]
    assert result.counters["targets"] == 4
    assert result.counters["up_to_date"] == 4


def test_live_bead_wait_forces_a_beads_target_without_auto_sync_opt_in(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_sidecar_sync(
        monkeypatch,
        tmp_path,
        records=[make_project(tmp_path)],
        roles_by_project={},
        live_bead_wait_projects=frozenset({"proj"}),
    )
    sync = MagicMock(
        return_value=SidecarSyncResult("proj", "beads", "refreshed", "fast-forwarded")
    )
    monkeypatch.setattr(sidecar_sync_chop, "sync_primary_sidecar_role", sync)

    result = sidecar_sync_chop._run(make_runtime(tmp_path))

    sync.assert_called_once()
    args, kwargs = sync.call_args
    assert args[0] == "proj"
    assert args[1] == "beads"
    assert kwargs["require_auto_sync_opt_in"] is False
    assert result.counters["targets"] == 1
    assert result.counters["refreshed"] == 1
    sidecar_sync_chop.mark_sidecar_sync_hint.assert_called_once_with("proj", "beads")


def test_live_bead_wait_does_not_duplicate_an_already_opted_in_beads_role(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_sidecar_sync(
        monkeypatch,
        tmp_path,
        records=[make_project(tmp_path)],
        roles_by_project={"proj": ("beads",)},
        live_bead_wait_projects=frozenset({"proj"}),
    )
    sync = MagicMock(
        return_value=SidecarSyncResult("proj", "beads", "up_to_date", "already fresh")
    )
    monkeypatch.setattr(sidecar_sync_chop, "sync_primary_sidecar_role", sync)

    result = sidecar_sync_chop._run(make_runtime(tmp_path))

    sync.assert_called_once()
    _args, kwargs = sync.call_args
    assert kwargs["require_auto_sync_opt_in"] is True
    assert result.counters["targets"] == 1


def test_bead_refresh_mode_off_skips_the_live_wait_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_sidecar_sync(
        monkeypatch,
        tmp_path,
        records=[make_project(tmp_path)],
        roles_by_project={},
        bead_refresh_mode="off",
    )
    monkeypatch.setattr(
        sidecar_sync_chop,
        "_projects_with_live_bead_waits",
        lambda _root: pytest.fail("disabled bead refresh scanned artifacts"),
    )

    result = sidecar_sync_chop._run(make_runtime(tmp_path))

    assert result.reason == "no_auto_sync_roles"
    sidecar_sync_chop.mark_sidecar_sync_hint.assert_not_called()
