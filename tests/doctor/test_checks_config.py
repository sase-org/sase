"""Tests for Phase 2 doctor config checks."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml

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


def test_config_layers_warns_on_deprecated_sibling_repos(tmp_path: Path) -> None:
    """A legacy ``sibling_repos:`` config triggers a non-fatal doctor warning."""
    (tmp_path / "sase.yml").write_text(
        yaml.dump(
            {
                "sibling_repos": [
                    {"name": "core", "path": "../sase-core", "description": "core"}
                ]
            }
        ),
        encoding="utf-8",
    )

    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "workspace"),
    ):
        check = _check_config_layers()

    assert check.status == "WARN"
    detail_text = " ".join(check.details)
    assert "deprecated" in detail_text
    assert "sibling_repos -> linked_repos" in detail_text
