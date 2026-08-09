"""Tests for the ACE navigation and information widgets."""

from unittest.mock import patch

from sase.ace.testing import AcePage, make_patch
from sase.ace.tui import AceApp
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets import PatchInfoPanel, TabBar


def test_tab_bar_update_tab_to_agents() -> None:
    """Test that update_tab changes the current tab to agents."""
    tab_bar = TabBar()
    tab_bar.update_tab("agents")
    assert tab_bar._current_tab == "agents"


def test_tab_bar_patch_tab_label_is_artifacts() -> None:
    tab_bar = TabBar()
    plain = tab_bar._build_content().plain
    assert " Artifacts " in plain
    assert " PRs " not in plain
    assert " Patches " not in plain


def test_tab_bar_label_order_is_agents_artifacts_axe() -> None:
    tab_bar = TabBar()
    plain = tab_bar._build_content().plain
    assert plain.index("Agents") < plain.index("Artifacts") < plain.index("AXE")


def test_info_panel_fold_indicator_hidden_when_all_collapsed() -> None:
    """No fold indicator when all sections are collapsed (default)."""
    panel = PatchInfoPanel()
    content = panel._build_content()
    assert "▸" not in content.plain
    assert "▾" not in content.plain
    assert "▼" not in content.plain


def test_info_panel_fold_indicator_shown_when_any_expanded() -> None:
    """Fold indicator appears when any section is non-collapsed."""
    panel = PatchInfoPanel()
    panel._fold_commits = FoldLevel.EXPANDED
    content = panel._build_content()
    # c▾h▸m▸ (labels interleaved with indicators)
    assert "c▾" in content.plain
    assert "h▸" in content.plain
    assert "m▸" in content.plain


def test_info_panel_fold_indicator_all_fully_expanded() -> None:
    """All sections fully expanded shows three heavy down arrows."""
    panel = PatchInfoPanel()
    panel._fold_commits = FoldLevel.FULLY_EXPANDED
    panel._fold_hooks = FoldLevel.FULLY_EXPANDED
    panel._fold_mentors = FoldLevel.FULLY_EXPANDED
    content = panel._build_content()
    assert "c▼" in content.plain
    assert "h▼" in content.plain
    assert "m▼" in content.plain


def test_info_panel_fold_indicator_mixed_states() -> None:
    """Mixed fold states show correct character per section."""
    panel = PatchInfoPanel()
    panel._fold_commits = FoldLevel.FULLY_EXPANDED
    panel._fold_hooks = FoldLevel.COLLAPSED
    panel._fold_mentors = FoldLevel.EXPANDED
    content = panel._build_content()
    assert "c▼" in content.plain
    assert "h▸" in content.plain
    assert "m▾" in content.plain


async def test_tab_bar_integration_tab_key() -> None:
    """Test that pressing TAB key cycles through all tabs."""
    patches = [make_patch()]
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=patches) as page:
            # Initial state - patches tab
            await page.expect_state("tab", "patches")

            # Press TAB to switch to axe (PRs -> AXE in the new order)
            await page.press("tab")
            await page.expect_state("tab", "axe")

            # Press TAB to switch to agents
            await page.press("tab")
            await page.expect_state("tab", "agents")

            # Press TAB to cycle back to patches
            await page.press("tab")
            await page.expect_state("tab", "patches")
