"""Pytest fixtures for ``sase notify`` tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture()
def temp_notifications_dir(tmp_path: Path) -> Iterator[Path]:
    notifications_dir = str(tmp_path / "notifications")
    notifications_file = str(tmp_path / "notifications" / "notifications.jsonl")
    with (
        patch("sase.notifications.store.NOTIFICATIONS_DIR", notifications_dir),
        patch("sase.notifications.store.NOTIFICATIONS_FILE", notifications_file),
        patch.dict("sase.notifications.store._LOAD_CACHE", {}, clear=True),
    ):
        yield tmp_path
