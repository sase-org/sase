"""End-to-end tests for remapped keybindings via the AcePage testing DSL."""

from unittest.mock import patch

from sase.ace.testing import AcePage


def _patch_config(overrides: dict | None = None):
    """Patch load_merged_config to return custom ace keymaps config."""
    cfg: dict = {"ace": {}}
    if overrides:
        cfg["ace"]["keymaps"] = overrides
    return patch("sase.config.load_merged_config", return_value=cfg)


async def test_default_keys_still_work() -> None:
    """With no config override, default 'j' key navigates down."""
    with _patch_config():
        async with AcePage() as page:
            await page.press("j")
            await page.expect_state("idx", 1)


async def test_remapped_navigation_key() -> None:
    """Remapping next_changespec to 'B' makes 'B' navigate and 'j' not."""
    keymap_cfg = {"app": {"next_changespec": "B"}}

    # 'B' should navigate
    with _patch_config(keymap_cfg):
        async with AcePage() as page:
            await page.press("B")
            await page.expect_state("idx", 1)

    # 'j' should no longer navigate
    with _patch_config(keymap_cfg):
        async with AcePage() as page:
            await page.press("j")
            await page.expect_state("idx", 0)
