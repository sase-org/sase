"""Pytest fixtures for machine-init tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.config import core as config_core
from tests.conftest import redirect_sase_home


@pytest.fixture
def isolated_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setattr(config_core, "CONFIG_DIR", config_dir)
    config_core.clear_config_cache()
    monkeypatch.setattr(
        "sase.dispatch.machine_service.validate_connection_plan",
        lambda record, **kwargs: (),
    )
    return config_dir, tmp_path / "credentials.json"
