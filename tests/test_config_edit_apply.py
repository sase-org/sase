"""Tests for config edit write execution and conflict handling."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from sase.config.edit import (
    AppliedResult,
    ConfigEditConflict,
    ConfigEditError,
    ConfigEditOp,
    apply_config_edit,
    plan_config_edit,
)
from tests._config_edit_helpers import (
    config_inventory,
    config_layer,
    user_file_inventory,
)


def test_apply_config_edit_writes_previewed_text(tmp_path: Path) -> None:
    """apply writes exactly the previewed text, preserving comments."""
    inventory, user_file = user_file_inventory(
        tmp_path,
        "# keep me\naxe:\n  max_hook_runners: 3  # runners\n",
        {"axe": {"max_hook_runners": 3}},
    )
    plan = plan_config_edit(
        inventory,
        "axe.max_hook_runners",
        "user",
        ConfigEditOp.set_value(9),
        use_chezmoi=False,
    )
    result = apply_config_edit(plan)
    assert isinstance(result, AppliedResult)
    assert result.path == str(user_file)
    assert result.created is False
    written = user_file.read_text(encoding="utf-8")
    assert written == plan.new_text
    assert "# keep me" in written
    assert "# runners" in written
    assert yaml.safe_load(written)["axe"]["max_hook_runners"] == 9


def test_apply_config_edit_creates_missing_file(tmp_path: Path) -> None:
    """apply creates a fresh target file (and parents) when absent."""
    target = tmp_path / "nested" / "sase.yml"
    layers = [
        config_layer("default", data={"timezone": "America/New_York"}),
        config_layer(
            "user", path=str(target), strategy="replace", data={}, exists=False
        ),
    ]
    inventory = config_inventory(layers)
    plan = plan_config_edit(
        inventory,
        "timezone",
        "user",
        ConfigEditOp.set_value("UTC"),
        use_chezmoi=False,
    )
    result = apply_config_edit(plan)
    assert result.created is True
    assert yaml.safe_load(target.read_text(encoding="utf-8")) == {"timezone": "UTC"}


def test_apply_config_edit_without_target_raises() -> None:
    """apply refuses a plan that has no writable target file."""
    layers = [config_layer("default", data={"timezone": "America/New_York"})]
    inventory = config_inventory(layers)
    plan = plan_config_edit(
        inventory,
        "timezone",
        "default",
        ConfigEditOp.set_value("UTC"),
        use_chezmoi=False,
    )
    # The default layer is package-backed (no file), so there is no target.
    assert plan.target_path is None
    with pytest.raises(ConfigEditError):
        apply_config_edit(plan)


def test_apply_config_edit_rejects_stale_existing_target(tmp_path: Path) -> None:
    inventory, target = user_file_inventory(
        tmp_path,
        "timezone: US/Pacific\n",
        {"timezone": "America/New_York"},
    )
    plan = plan_config_edit(
        inventory,
        "timezone",
        "user",
        ConfigEditOp.set_value("UTC"),
        use_chezmoi=False,
    )
    target.write_text("timezone: Europe/London\n", encoding="utf-8")
    with (
        patch("sase.config._edit_plan.clear_config_cache") as clear_cache,
        pytest.raises(ConfigEditConflict),
    ):
        apply_config_edit(plan)
    assert target.read_text(encoding="utf-8") == "timezone: Europe/London\n"
    clear_cache.assert_not_called()


def test_apply_config_edit_rejects_stale_absent_target(tmp_path: Path) -> None:
    target = tmp_path / "new" / "sase.yml"
    inventory = config_inventory(
        [
            config_layer("default", data={"timezone": "America/New_York"}),
            config_layer(
                "user",
                path=str(target),
                strategy="replace",
                data={},
                exists=False,
            ),
        ]
    )
    plan = plan_config_edit(
        inventory,
        "timezone",
        "user",
        ConfigEditOp.set_value("UTC"),
        use_chezmoi=False,
    )
    target.parent.mkdir(parents=True)
    target.write_text("timezone: Asia/Tokyo\n", encoding="utf-8")
    with pytest.raises(ConfigEditConflict):
        apply_config_edit(plan)
    assert target.read_text(encoding="utf-8") == "timezone: Asia/Tokyo\n"


def test_apply_config_edit_preserves_mode_and_clears_cache_after_replace(
    tmp_path: Path,
) -> None:
    inventory, target = user_file_inventory(
        tmp_path,
        "timezone: US/Pacific\n",
        {"timezone": "America/New_York"},
    )
    target.chmod(0o640)
    plan = plan_config_edit(
        inventory,
        "timezone",
        "user",
        ConfigEditOp.set_value("UTC"),
        use_chezmoi=False,
    )
    with patch("sase.config._edit_plan.clear_config_cache") as clear_cache:
        apply_config_edit(plan)
        assert target.read_text(encoding="utf-8") == plan.new_text
        clear_cache.assert_called_once_with()
    assert target.stat().st_mode & 0o777 == 0o640


def test_apply_config_edit_replace_failure_keeps_original_and_cleans_temp(
    tmp_path: Path,
) -> None:
    original = "timezone: US/Pacific\n"
    inventory, target = user_file_inventory(
        tmp_path,
        original,
        {"timezone": "America/New_York"},
    )
    plan = plan_config_edit(
        inventory,
        "timezone",
        "user",
        ConfigEditOp.set_value("UTC"),
        use_chezmoi=False,
    )
    with (
        patch("sase.config._edit_plan.os.replace", side_effect=OSError("boom")),
        patch("sase.config._edit_plan.clear_config_cache") as clear_cache,
        pytest.raises(OSError, match="boom"),
    ):
        apply_config_edit(plan)
    assert target.read_text(encoding="utf-8") == original
    assert list(tmp_path.glob(f".{target.name}.*.tmp")) == []
    clear_cache.assert_not_called()
