"""Tests for Phase 2 doctor config checks."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sase.config.core import load_config_layers
from sase.doctor.checks_config import _check_config_layers


def test_config_layers_report_invalid_existing_yaml(tmp_path: Path) -> None:
    (tmp_path / "sase.yml").write_text("invalid: yaml: [not closed", encoding="utf-8")

    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "workspace"),
    ):
        layers = load_config_layers()
        check = _check_config_layers()

    user_layer = next(layer for layer in layers if layer.name == "user")
    assert user_layer.present is True
    assert user_layer.exists is False
    assert user_layer.error is not None
    assert check.status == "WARN"
    assert "sase.yml" in check.details[0]
