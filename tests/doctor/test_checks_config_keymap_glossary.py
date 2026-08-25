"""Tests for the doctor Glossary keymap-scope deprecation check."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml

from sase.doctor.checks_config_keymap_glossary import check_config_keymap_glossary


def test_keymap_glossary_warns_when_user_config_sets_glossary_scope(
    tmp_path: Path,
) -> None:
    """A layer that still sets ``ace.keymaps.glossary`` triggers a WARN."""
    (tmp_path / "sase.yml").write_text(
        yaml.dump({"ace": {"keymaps": {"glossary": {"next_term": "down"}}}}),
        encoding="utf-8",
    )

    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "workspace"),
    ):
        check = check_config_keymap_glossary()

    assert check.status == "WARN"
    detail_text = " ".join(check.details)
    assert "ace.keymaps.glossary -> ace.keymaps.memory" in detail_text
    assert check.data["problems"]


def test_keymap_glossary_ok_when_absent(tmp_path: Path) -> None:
    """No WARN when no layer sets the retired ``ace.keymaps.glossary`` scope."""
    (tmp_path / "sase.yml").write_text(
        yaml.dump({"ace": {"keymaps": {"memory": {"next_note": "down"}}}}),
        encoding="utf-8",
    )

    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "workspace"),
    ):
        check = check_config_keymap_glossary()

    assert check.status == "OK"
    assert check.data["problems"] == ()


def test_keymap_glossary_ok_with_no_ace_config_at_all(tmp_path: Path) -> None:
    """A user config that never mentions ``ace`` at all is not flagged."""
    (tmp_path / "sase.yml").write_text("id:\n  machine_name: test\n", encoding="utf-8")

    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "workspace"),
    ):
        check = check_config_keymap_glossary()

    assert check.status == "OK"
    assert check.data["problems"] == ()
