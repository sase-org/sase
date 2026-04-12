"""Tests for the ace testing DSL (AcePage)."""

from sase.ace.testing import AcePage, make_changespec


async def test_ace_page_initial_state() -> None:
    """AcePage returns expected state dict after entering context."""
    async with AcePage() as page:
        state = page.state
        assert state["idx"] == 0
        assert state["total"] == 3
        assert state["tab"] == "changespecs"
        assert state["modal"] is None
        assert state["selected"]["name"] == "feature_a"


async def test_ace_page_press() -> None:
    """Pressing 'j' changes the current index."""
    async with AcePage() as page:
        assert page.state["idx"] == 0
        await page.press("j")
        assert page.state["idx"] == 1


async def test_ace_page_screen() -> None:
    """Screen property returns non-empty string."""
    async with AcePage() as page:
        screen = page.screen
        assert isinstance(screen, str)
        assert len(screen) > 0


async def test_ace_page_custom_changespecs() -> None:
    """Passing custom changespecs overrides defaults."""
    custom = [
        make_changespec(name="custom_a"),
        make_changespec(name="custom_b"),
    ]
    async with AcePage(query='"custom"', changespecs=custom) as page:
        state = page.state
        assert state["total"] == 2
        assert state["selected"]["name"] == "custom_a"
