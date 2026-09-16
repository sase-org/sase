"""Tests for machine-selected config identity overlays."""

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.config.core import (
    get_agent_owner_identity,
    get_machine_name,
    load_config_layers,
    load_merged_config,
    load_xprompts_by_source,
    require_agent_owner_identity,
    require_machine_name,
)
from sase.core.paths import machine_name_path


def test_machine_overlays_require_matching_selector_and_keep_ordinary_overlays(
    tmp_path: Path,
) -> None:
    (tmp_path / "sase_common.yml").write_text("common: true\n", encoding="utf-8")
    (tmp_path / "sase_athena.yml").write_text(
        "id:\n  username: alice\n  machine_name: athena\nselected: athena\n",
        encoding="utf-8",
    )
    (tmp_path / "sase_zeus.yml").write_text(
        "id:\n  username: alice\n  machine_name: zeus\nselected: zeus\n",
        encoding="utf-8",
    )

    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local"),
    ):
        without_selector = load_merged_config()
        assert without_selector["common"] is True
        assert "machine_name" not in without_selector
        assert "selected" not in without_selector

        machine_name_path().write_text("athena\n", encoding="utf-8")
        from sase.config.core import clear_config_cache

        clear_config_cache()
        selected = load_merged_config()

    assert selected["id"] == {"username": "alice", "machine_name": "athena"}
    assert "machine_name" not in selected
    assert selected["selected"] == "athena"
    assert selected["common"] is True


def test_machine_overlay_selection_is_shared_by_layers_and_xprompt_sources(
    tmp_path: Path,
) -> None:
    (tmp_path / "sase_common.yml").write_text(
        "xprompts:\n  common: common\n", encoding="utf-8"
    )
    (tmp_path / "sase_athena.yml").write_text(
        "id:\n  username: alice\n  machine_name: athena\n"
        "xprompts:\n  athena: selected\n",
        encoding="utf-8",
    )
    (tmp_path / "sase_zeus.yml").write_text(
        "id:\n  username: alice\n  machine_name: zeus\nxprompts:\n  zeus: foreign\n",
        encoding="utf-8",
    )
    machine_name_path().write_text("athena\n", encoding="utf-8")

    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local"),
    ):
        layer_names = {layer.name for layer in load_config_layers()}
        sources = dict(load_xprompts_by_source())

    assert "overlay:sase_common.yml" in layer_names
    assert "overlay:sase_athena.yml" in layer_names
    assert "overlay:sase_zeus.yml" not in layer_names
    assert sources["config_overlay:sase_common.yml"] == {"common": "common"}
    assert sources["config_overlay:sase_athena.yml"] == {"athena": "selected"}
    assert "config_overlay:sase_zeus.yml" not in sources


def test_owner_and_machine_accessors_require_complete_selected_overlay(
    tmp_path: Path,
) -> None:
    (tmp_path / "sase_athena.yml").write_text(
        "id:\n  username: alice\n  machine_name: athena\n", encoding="utf-8"
    )
    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local"),
    ):
        assert get_machine_name() is None
        assert get_agent_owner_identity() is None
        with pytest.raises(RuntimeError, match="sase config init"):
            require_machine_name()

        machine_name_path().write_text("athena\n", encoding="utf-8")
        from sase.config.core import clear_config_cache

        clear_config_cache()
        owner = require_agent_owner_identity()
        assert owner.username == "alice"
        assert owner.machine_name == "athena"
        assert get_machine_name() == "athena"
        assert require_machine_name() == "athena"


def test_legacy_overlay_is_discovered_but_not_a_complete_owner(
    tmp_path: Path,
) -> None:
    (tmp_path / "sase_athena.yml").write_text(
        "machine_name: athena\n", encoding="utf-8"
    )
    machine_name_path().write_text("athena\n", encoding="utf-8")

    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local"),
    ):
        from sase.config.core import discover_machine_names

        assert discover_machine_names() == ("athena",)
        assert get_agent_owner_identity() is None
        with pytest.raises(RuntimeError, match="id.username"):
            require_agent_owner_identity()


def test_selected_overlay_identity_cannot_be_overridden_by_other_sources(
    tmp_path: Path,
) -> None:
    (tmp_path / "sase.yml").write_text(
        "id:\n  username: mallory\n  machine_name: zeus\n", encoding="utf-8"
    )
    (tmp_path / "sase_common.yml").write_text(
        "id:\n  username: other\nordinary: true\n", encoding="utf-8"
    )
    (tmp_path / "sase_athena.yml").write_text(
        "id:\n  username: alice\n  machine_name: athena\nselected: true\n",
        encoding="utf-8",
    )
    machine_name_path().write_text("athena\n", encoding="utf-8")

    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local"),
    ):
        merged = load_merged_config()
        owner = require_agent_owner_identity()

    assert owner.username == "alice"
    assert merged["id"] == {"username": "alice", "machine_name": "athena"}
    assert merged["ordinary"] is True


@pytest.mark.parametrize("selector", ["Athena", "athena-1", "athena\nzeus\n"])
def test_invalid_machine_selector_never_selects_overlay(
    tmp_path: Path,
    selector: str,
) -> None:
    (tmp_path / "sase_athena.yml").write_text(
        "machine_name: athena\nprivate_value: true\n", encoding="utf-8"
    )
    machine_name_path().write_text(selector, encoding="utf-8")

    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local"),
    ):
        result = load_merged_config()

    assert "machine_name" not in result
    assert "private_value" not in result
