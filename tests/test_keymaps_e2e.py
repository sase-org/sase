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


async def test_ctrl_at_dispatches_repeat_agent_binding_not_bare_space() -> None:
    """Ctrl+Space's runtime key dispatches the repeat-agent action."""
    with _patch_config():
        async with AcePage() as page:
            calls: list[bool] = []

            def _record_repeat_agent() -> None:
                calls.append(True)

            page.app.action_start_agent_from_changespec = _record_repeat_agent  # type: ignore[method-assign]

            await page.press("space")
            assert calls == []

            await page.press("ctrl+@")
            assert calls == [True]


async def test_leader_space_dispatches_agent_home_not_bare_space() -> None:
    """Bare Space launches home-mode agents only after leader mode is active."""
    with _patch_config():
        async with AcePage() as page:
            calls: list[bool] = []

            def _record_agent_home() -> None:
                calls.append(True)

            page.app._show_prompt_input_bar_for_home = _record_agent_home  # type: ignore[method-assign]

            await page.press("space")
            assert calls == []

            await page.press("comma", "space")
            assert calls == [True]
