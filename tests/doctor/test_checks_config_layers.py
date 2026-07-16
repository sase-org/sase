"""Tests for doctor config layer checks."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml

from sase.config.core import load_config_layers
from sase.doctor.checks_config_layers import check_config_layers


def test_config_layers_report_invalid_existing_yaml(tmp_path: Path) -> None:
    (tmp_path / "sase.yml").write_text("invalid: yaml: [not closed", encoding="utf-8")

    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "workspace"),
    ):
        layers = load_config_layers()
        check = check_config_layers()

    user_layer = next(layer for layer in layers if layer.name == "user")
    assert user_layer.present is True
    assert user_layer.exists is False
    assert user_layer.error is not None
    assert check.status == "WARN"
    assert "sase.yml" in check.details[0]


def test_config_layers_reports_project_layout_collision(tmp_path: Path) -> None:
    project = tmp_path / "project"
    canonical = project / "sase" / "sase.yml"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("canonical: true\n", encoding="utf-8")
    (project / "sase.yml").write_text("legacy: true\n", encoding="utf-8")

    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path / "config"),
        patch("sase.config.core.Path.cwd", return_value=project),
    ):
        check = check_config_layers()

    assert check.status == "ERROR"
    assert check.data["collision_paths"] == (
        str(canonical),
        str(project / "sase.yml"),
    )


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
        check = check_config_layers()

    assert check.status == "WARN"
    detail_text = " ".join(check.details)
    assert "deprecated" in detail_text
    assert "sibling_repos -> repos.linked" in detail_text


def test_config_layers_warns_on_deprecated_linked_repos(tmp_path: Path) -> None:
    (tmp_path / "sase.yml").write_text(
        yaml.dump(
            {
                "linked_repos": [
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
        check = check_config_layers()

    assert check.status == "WARN"
    assert any("linked_repos -> repos.linked" in detail for detail in check.details)


def test_config_layers_warns_on_retired_sdd_selectors(tmp_path: Path) -> None:
    (tmp_path / "sase.yml").write_text(
        "sdd:\n  storage: local\n  version_controlled: true\n",
        encoding="utf-8",
    )

    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "workspace"),
    ):
        check = check_config_layers()

    assert check.status == "WARN"
    detail_text = " ".join(check.details)
    assert "retired keys ignored" in detail_text
    assert "sdd.storage" in detail_text
    assert "sdd.version_controlled" in detail_text
