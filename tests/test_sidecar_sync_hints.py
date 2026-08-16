"""Durable primary-sidecar sync-hint persistence tests."""

from __future__ import annotations

from pathlib import Path

import pytest

import sase._sidecar_sync_hints as hints


@pytest.fixture(autouse=True)
def _isolated_sase_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hints, "sase_subdir", lambda name: tmp_path / name)


def test_marked_hint_is_pending() -> None:
    hints.mark_sidecar_sync_hint("proj", "plans")

    assert hints.pending_sidecar_sync_roles("proj") == ("plans",)


def test_marking_the_same_role_twice_does_not_duplicate() -> None:
    hints.mark_sidecar_sync_hint("proj", "plans")
    hints.mark_sidecar_sync_hint("proj", "plans")

    assert hints.pending_sidecar_sync_roles("proj") == ("plans",)


def test_multiple_roles_are_independent() -> None:
    hints.mark_sidecar_sync_hint("proj", "plans")
    hints.mark_sidecar_sync_hint("proj", "beads")

    assert set(hints.pending_sidecar_sync_roles("proj")) == {"plans", "beads"}


def test_projects_are_independent() -> None:
    hints.mark_sidecar_sync_hint("proj-a", "plans")

    assert hints.pending_sidecar_sync_roles("proj-b") == ()


def test_clear_consumes_one_role_without_disturbing_others() -> None:
    hints.mark_sidecar_sync_hint("proj", "plans")
    hints.mark_sidecar_sync_hint("proj", "beads")

    hints.clear_sidecar_sync_hint("proj", "plans")

    assert hints.pending_sidecar_sync_roles("proj") == ("beads",)


def test_clearing_an_unmarked_role_is_a_no_op() -> None:
    hints.mark_sidecar_sync_hint("proj", "plans")

    hints.clear_sidecar_sync_hint("proj", "beads")

    assert hints.pending_sidecar_sync_roles("proj") == ("plans",)


def test_no_hints_file_yields_no_pending_roles() -> None:
    assert hints.pending_sidecar_sync_roles("never-touched") == ()


def test_corrupt_hints_file_is_treated_as_empty(tmp_path: Path) -> None:
    path = tmp_path / "sidecar_sync_hints" / "proj.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not-json", encoding="utf-8")

    assert hints.pending_sidecar_sync_roles("proj") == ()
