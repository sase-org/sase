"""Tests for daemon read model parity with direct loaders."""

from __future__ import annotations

import dataclasses
import shutil
from pathlib import Path

import pytest

from sase.bead.project import BeadProject
from sase.daemon.read_models import (
    bead_list_from_dict,
    notification_list_from_dict,
)
from sase.notifications import store as notification_store

from tests._daemon_read_facade_helpers import (
    FIXTURE_ROOT,
    _bead_page,
    _issue_wire,
    _notification_page,
)


def test_notification_read_model_matches_direct_fixture_loader(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    notification_store._invalidate_load_cache()
    fixture_path = tmp_path / "notifications.jsonl"
    shutil.copy2(FIXTURE_ROOT / "notifications" / "notifications.jsonl", fixture_path)
    monkeypatch.setattr(notification_store, "NOTIFICATIONS_FILE", str(fixture_path))
    direct = notification_store.load_notifications(include_dismissed=False)

    daemon = notification_list_from_dict(
        _notification_page([dataclasses.asdict(item) for item in direct])
    )

    assert [item.id for item in daemon.notifications] == [item.id for item in direct]


def test_bead_read_model_matches_direct_fixture_loader(tmp_path: Path) -> None:
    shutil.copytree(FIXTURE_ROOT / "beads", tmp_path / "sdd" / "beads")
    with BeadProject(tmp_path) as project:
        direct = project.list_issues()

    daemon = bead_list_from_dict(_bead_page([_issue_wire(item) for item in direct]))

    assert [item.id for item in daemon.issues] == [item.id for item in direct]
