"""Tests for config layer metadata."""

from pathlib import Path
from unittest.mock import patch

import yaml

from sase.config.core import load_config_layers, load_merged_config


def test_load_config_layers_returns_default_layer(tmp_path: Path) -> None:
    """Default layer is always present and loaded."""
    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path / "empty"),
        patch("sase.config.core.Path.cwd", return_value=tmp_path),
    ):
        layers = load_config_layers()

    default_layers = [ly for ly in layers if ly.name == "default"]
    assert len(default_layers) == 1
    assert default_layers[0].exists is True
    assert default_layers[0].path is None


def test_load_config_layers_includes_user_and_local(tmp_path: Path) -> None:
    """User and local layers appear with correct metadata."""
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "sase.yml").write_text(yaml.dump({"key": "user"}))

    local_dir = tmp_path / "local"
    local_dir.mkdir()
    (local_dir / "sase.yml").write_text(yaml.dump({"extra": "local"}))

    with (
        patch("sase.config.core.CONFIG_DIR", global_dir),
        patch("sase.config.core.Path.cwd", return_value=local_dir),
    ):
        layers = load_config_layers()

    user_layer = next(ly for ly in layers if ly.name == "user")
    assert user_layer.exists is True
    assert user_layer.list_strategy == "replace"
    assert "key" in user_layer.keys

    local_layer = next(ly for ly in layers if ly.name == "local")
    assert local_layer.exists is True
    assert local_layer.list_strategy == "concatenate"
    assert "extra" in local_layer.keys


def test_load_config_layers_overlay_detected(tmp_path: Path) -> None:
    """Overlay files are detected as separate layers."""
    (tmp_path / "sase.yml").write_text(yaml.dump({"base": True}))
    (tmp_path / "sase_extra.yml").write_text(yaml.dump({"overlay_key": True}))

    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "none"),
    ):
        layers = load_config_layers()

    overlay_layers = [ly for ly in layers if ly.name.startswith("overlay:")]
    assert len(overlay_layers) == 1
    assert overlay_layers[0].name == "overlay:sase_extra.yml"
    assert "overlay_key" in overlay_layers[0].keys


def test_load_config_layers_missing_local_marked_not_found(tmp_path: Path) -> None:
    """When no local sase.yml exists, local layer is marked exists=False."""
    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path / "empty"),
        patch("sase.config.core.Path.cwd", return_value=tmp_path),
    ):
        layers = load_config_layers()

    local_layer = next(ly for ly in layers if ly.name == "local")
    assert local_layer.exists is False
    assert local_layer.keys == []


def test_load_config_layers_flags_unsupported_workflows_key(tmp_path: Path) -> None:
    """A top-level ``workflows:`` block is reported as unsupported, not merged in."""
    (tmp_path / "sase.yml").write_text(yaml.dump({"base": True}))
    (tmp_path / "sase_athena.yml").write_text(
        yaml.dump(
            {
                "workflows": {
                    "refresh_docs": {"steps": [{"bash": "echo hi"}]},
                }
            }
        )
    )

    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "none"),
    ):
        layers = load_config_layers()

    overlay_layer = next(ly for ly in layers if ly.name == "overlay:sase_athena.yml")
    assert overlay_layer.unsupported_keys == ["workflows"]


def test_load_config_layers_flags_deprecated_sibling_repos_key(
    tmp_path: Path,
) -> None:
    """A legacy ``sibling_repos:`` block is parsed but flagged as deprecated."""
    (tmp_path / "sase.yml").write_text(
        yaml.dump(
            {
                "sibling_repos": [
                    {"name": "core", "path": "../sase-core", "description": "core"}
                ]
            }
        )
    )

    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "none"),
    ):
        layers = load_config_layers()

    user_layer = next(ly for ly in layers if ly.name == "user")
    assert user_layer.deprecated_keys == ["sibling_repos"]
    # Deprecated keys are still real keys, not unsupported/ignored.
    assert "sibling_repos" in user_layer.keys
    assert user_layer.unsupported_keys == []


def test_load_config_layers_flags_deprecated_linked_repos_key(
    tmp_path: Path,
) -> None:
    (tmp_path / "sase.yml").write_text(
        yaml.dump(
            {
                "linked_repos": [
                    {"name": "core", "path": "../sase-core", "description": "core"}
                ]
            }
        )
    )

    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "none"),
    ):
        layers = load_config_layers()

    user_layer = next(ly for ly in layers if ly.name == "user")
    assert user_layer.deprecated_keys == ["linked_repos"]


def test_load_config_layers_canonical_repos_linked_not_deprecated(
    tmp_path: Path,
) -> None:
    """The canonical ``repos.linked:`` key is not flagged as deprecated."""
    (tmp_path / "sase.yml").write_text(
        yaml.dump(
            {
                "repos": {
                    "linked": [
                        {
                            "name": "core",
                            "path": "../sase-core",
                            "description": "core",
                        }
                    ]
                }
            }
        )
    )

    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "none"),
    ):
        layers = load_config_layers()

    user_layer = next(ly for ly in layers if ly.name == "user")
    assert user_layer.deprecated_keys == []


def test_load_config_ignores_retired_sdd_selectors(tmp_path: Path) -> None:
    (tmp_path / "sase.yml").write_text(
        "sdd:\n  storage: in_tree\n  version_controlled: true\n  push_after_commit: false\n",
        encoding="utf-8",
    )

    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "none"),
    ):
        layers = load_config_layers()
        merged = load_merged_config()

    user_layer = next(ly for ly in layers if ly.name == "user")
    assert user_layer.retired_keys == ["sdd.storage", "sdd.version_controlled"]
    assert merged["sdd"]["push_after_commit"] is False
    assert "storage" not in merged["sdd"]
    assert "version_controlled" not in merged["sdd"]
