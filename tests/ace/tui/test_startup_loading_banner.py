"""Tests for the bold centered startup loading banner."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from sase.ace.tui.app import AceApp
from sase.ace.tui.widgets.startup_loading_banner import StartupLoadingBanner


class _FakeBanner:
    """Stand-in for the mounted StartupLoadingBanner used in helper tests."""

    def __init__(self) -> None:
        self._classes: set[str] = set()

    def has_class(self, name: str) -> bool:
        return name in self._classes

    def add_class(self, name: str) -> None:
        self._classes.add(name)

    def hide(self) -> None:
        if not self.has_class("-hidden"):
            self.add_class("-hidden")


class _FakeAppBase:
    """Minimal state holder driving ``_maybe_hide_startup_banner`` in isolation."""

    def __init__(
        self,
        agents_done: bool,
        axe_done: bool,
        banner: _FakeBanner | None,
    ) -> None:
        self._agents_first_load_done = agents_done
        self._axe_first_load_done = axe_done
        self._banner = banner

    def query_one(self, selector: str, _cls: Any) -> Any:
        assert selector == "#startup-loading-banner"
        if self._banner is None:
            raise RuntimeError("banner not mounted")
        return self._banner


# Bind the real methods from AceApp onto the fake. They depend only on
# the attributes we've stubbed above, so this exercises the real logic
# without spinning up a full Textual app context.
_FakeAppBase._is_initial_load_pending = AceApp._is_initial_load_pending  # type: ignore[attr-defined]
_FakeAppBase._maybe_hide_startup_banner = AceApp._maybe_hide_startup_banner  # type: ignore[attr-defined]


def test_banner_hide_is_idempotent() -> None:
    """Calling hide() twice only adds the class once."""
    banner = StartupLoadingBanner()
    # Fresh instance should have no -hidden class.
    assert not banner.has_class("-hidden")
    banner.hide()
    assert banner.has_class("-hidden")
    # Second call must not raise and must leave the class present.
    banner.hide()
    assert banner.has_class("-hidden")


def test_maybe_hide_noop_while_agents_pending() -> None:
    """Banner stays visible when only the axe load is finished."""
    banner = _FakeBanner()
    app = _FakeAppBase(agents_done=False, axe_done=True, banner=banner)
    app._maybe_hide_startup_banner()  # type: ignore[attr-defined]
    assert not banner.has_class("-hidden")


def test_maybe_hide_noop_while_axe_pending() -> None:
    """Banner stays visible when only the agents load is finished."""
    banner = _FakeBanner()
    app = _FakeAppBase(agents_done=True, axe_done=False, banner=banner)
    app._maybe_hide_startup_banner()  # type: ignore[attr-defined]
    assert not banner.has_class("-hidden")


def test_maybe_hide_hides_once_both_done() -> None:
    """Banner is hidden as soon as both flags are True."""
    banner = _FakeBanner()
    app = _FakeAppBase(agents_done=True, axe_done=True, banner=banner)
    app._maybe_hide_startup_banner()  # type: ignore[attr-defined]
    assert banner.has_class("-hidden")


def test_maybe_hide_tolerates_missing_banner() -> None:
    """If the banner cannot be queried, the helper swallows the error."""
    app = _FakeAppBase(agents_done=True, axe_done=True, banner=None)
    # Should not raise even when query_one would.
    app._maybe_hide_startup_banner()  # type: ignore[attr-defined]


def test_maybe_hide_second_finisher_agents() -> None:
    """Sequential flip — axe first, then agents — triggers exactly one hide."""
    banner = _FakeBanner()
    app = _FakeAppBase(agents_done=False, axe_done=True, banner=banner)
    app._maybe_hide_startup_banner()  # type: ignore[attr-defined]
    assert not banner.has_class("-hidden")
    app._agents_first_load_done = True
    app._maybe_hide_startup_banner()  # type: ignore[attr-defined]
    assert banner.has_class("-hidden")


def test_maybe_hide_second_finisher_axe() -> None:
    """Sequential flip — agents first, then axe — triggers exactly one hide."""
    banner = _FakeBanner()
    app = _FakeAppBase(agents_done=True, axe_done=False, banner=banner)
    app._maybe_hide_startup_banner()  # type: ignore[attr-defined]
    assert not banner.has_class("-hidden")
    app._axe_first_load_done = True
    app._maybe_hide_startup_banner()  # type: ignore[attr-defined]
    assert banner.has_class("-hidden")


def test_banner_does_not_reappear_after_subsequent_refresh() -> None:
    """Refreshes after the banner is hidden leave it hidden."""
    banner = _FakeBanner()
    app = _FakeAppBase(agents_done=True, axe_done=True, banner=banner)
    app._maybe_hide_startup_banner()  # type: ignore[attr-defined]
    assert banner.has_class("-hidden")
    # Simulate additional auto-refresh cycles.
    for _ in range(3):
        app._maybe_hide_startup_banner()  # type: ignore[attr-defined]
    # Still hidden, class list unchanged.
    assert banner.has_class("-hidden")


def test_is_initial_load_pending_truth_table() -> None:
    """The derived property is True unless both flags are True."""
    for agents, axe, expected in [
        (False, False, True),
        (True, False, True),
        (False, True, True),
        (True, True, False),
    ]:
        app = _FakeAppBase(agents_done=agents, axe_done=axe, banner=None)
        # Access the real property from AceApp, bound to the fake.
        assert app._is_initial_load_pending is expected  # type: ignore[attr-defined]


def test_banner_widget_compose_yields_spinner_and_label() -> None:
    """The banner's compose produces exactly spinner + label in that order."""
    banner = StartupLoadingBanner()
    children = list(banner.compose())
    assert len(children) == 2
    assert children[0].id == "startup-loading-banner-spinner"
    assert children[1].id == "startup-loading-banner-label"


def test_maybe_hide_accepts_non_banner_query_errors() -> None:
    """A raising query_one is swallowed without propagating."""

    class _RaisingApp(_FakeAppBase):
        def query_one(self, selector: str, _cls: Any) -> Any:
            raise LookupError("not mounted yet")

    app = _RaisingApp(agents_done=True, axe_done=True, banner=None)
    # Must not raise.
    app._maybe_hide_startup_banner()  # type: ignore[attr-defined]


def test_maybe_hide_queries_correct_selector() -> None:
    """Verifies the helper queries the banner by its canonical id."""
    banner = _FakeBanner()
    app = _FakeAppBase(agents_done=True, axe_done=True, banner=banner)
    app.query_one = MagicMock(wraps=app.query_one)  # type: ignore[method-assign]
    app._maybe_hide_startup_banner()  # type: ignore[attr-defined]
    app.query_one.assert_called_once()
    args, _ = app.query_one.call_args
    assert args[0] == "#startup-loading-banner"
    assert args[1] is StartupLoadingBanner
