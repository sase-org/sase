"""Launch-tab chip states on the prompt dispatch context line (sase-1bc.10)."""

from __future__ import annotations

from types import SimpleNamespace

from textual.widgets import Static

import pytest

from sase.ace.tui.widgets._prompt_input_bar_dispatch import (
    PromptInputBarDispatchMixin,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.renderable_text import renderable_to_text
from sase.core.agent_tab import AgentTabCatalogEntry, AgentTabKey
from tests.ace.tui.widgets.test_dispatch_target_picker_focus import (
    DispatchPickerFocusApp,
    _seed_remote_targets,
)


@pytest.fixture
def no_catalog_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        PromptInputBarDispatchMixin,
        "_warm_dispatch_target_catalog",
        lambda self: None,
    )


def _enable_tabs(app: DispatchPickerFocusApp) -> None:
    app.current_tab = "agents"  # type: ignore[attr-defined]
    app._active_agent_tab = AgentTabKey.default()


async def test_explicit_tab_shows_chip(
    no_catalog_worker: None,
) -> None:
    app = DispatchPickerFocusApp("%tab:blog\n#gh:sase")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        _enable_tabs(app)
        bar = app.query_one(PromptInputBar)
        _seed_remote_targets(bar)
        bar._refresh_dispatch_context_line()
        await pilot.pause()

        panel = app.query_one("#prompt-dispatch-context", Static)
        assert not panel.has_class("hidden")
        rendered = renderable_to_text(panel.render())
        assert rendered is not None
        assert "Tab" in rendered
        assert "blog" in rendered
        assert "Ctrl+G b change" in rendered


async def test_explicit_default_tab_shows_default(
    no_catalog_worker: None,
) -> None:
    app = DispatchPickerFocusApp("%tab:main\n#gh:sase")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        _enable_tabs(app)
        bar = app.query_one(PromptInputBar)
        _seed_remote_targets(bar)
        bar._refresh_dispatch_context_line()
        await pilot.pause()

        panel = app.query_one("#prompt-dispatch-context", Static)
        assert not panel.has_class("hidden")
        rendered = renderable_to_text(panel.render())
        assert rendered is not None
        assert "main (default)" in rendered


async def test_named_active_tab_shows_inherited_chip(
    no_catalog_worker: None,
) -> None:
    app = DispatchPickerFocusApp("#gh:sase")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        _enable_tabs(app)
        app._active_agent_tab = AgentTabKey.named("blog")
        bar = app.query_one(PromptInputBar)
        _seed_remote_targets(bar)
        bar._refresh_dispatch_context_line()
        await pilot.pause()

        panel = app.query_one("#prompt-dispatch-context", Static)
        assert not panel.has_class("hidden")
        rendered = renderable_to_text(panel.render())
        assert rendered is not None
        assert "blog" in rendered
        assert "from view" in rendered


async def test_default_active_tab_hides_chip(
    no_catalog_worker: None,
) -> None:
    app = DispatchPickerFocusApp("#gh:sase")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        _enable_tabs(app)
        bar = app.query_one(PromptInputBar)
        _seed_remote_targets(bar)
        bar._refresh_dispatch_context_line()
        await pilot.pause()

        panel = app.query_one("#prompt-dispatch-context", Static)
        assert panel.has_class("hidden")
        assert bar._dispatch_context_visible is False


async def test_remote_machine_tab_shows_runs_on_note(
    no_catalog_worker: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui import agent_tabs_settings as settings_mod
    from sase.ace.tui.agent_tabs_settings import AgentTabsViewConfig

    monkeypatch.setattr(
        settings_mod,
        "agent_tabs_view_config",
        lambda: AgentTabsViewConfig(
            machine_mode=True,
            machine_order=(("iid-apollo", "apollo"),),
            pinned_by_alias={"apollo": "iid-apollo"},
            named_order={},
            local_machine_name="athena",
            token=("prompt-context-test",),
        ),
    )
    app = DispatchPickerFocusApp("#gh:sase")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        _enable_tabs(app)
        key = AgentTabKey.machine("iid-apollo")
        app._active_agent_tab = key
        app._agent_tab_index = SimpleNamespace(
            catalog=(
                AgentTabCatalogEntry(AgentTabKey.default(), "default", "⌂ athena", 1),
                AgentTabCatalogEntry(key, "machine", "⌨ apollo", 2),
            )
        )
        app._agent_tab_latched_key = None
        bar = app.query_one(PromptInputBar)
        _seed_remote_targets(bar)
        bar._refresh_dispatch_context_line()
        await pilot.pause()

        panel = app.query_one("#prompt-dispatch-context", Static)
        assert not panel.has_class("hidden")
        rendered = renderable_to_text(panel.render())
        assert rendered is not None
        assert "runs on ⌂ athena" in rendered
        assert "gD launch on apollo" in rendered


def test_tab_matching_machine_alias_notes_named_win() -> None:
    """A named tab equal to a machine alias names the winner (pure)."""
    from sase.ace.tui.widgets._prompt_input_bar_dispatch import (
        PromptInputBarDispatchMixin,
    )

    mixin = PromptInputBarDispatchMixin.__new__(PromptInputBarDispatchMixin)
    mixin._dispatch_target_rows = {"apollo": {"alias": "apollo"}}
    segment = PromptInputBarDispatchMixin._named_tab_segment(
        mixin, "apollo", inherited=False
    )
    assert "named tab wins" in segment.plain


def test_tab_matching_local_name_notes_local_win(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A named tab equal to the local machine name names the home tab."""
    from sase.ace.tui import agent_tabs_settings as settings_mod
    from sase.ace.tui.agent_tabs_settings import AgentTabsViewConfig
    from sase.ace.tui.widgets._prompt_input_bar_dispatch import (
        PromptInputBarDispatchMixin,
    )

    monkeypatch.setattr(
        settings_mod,
        "agent_tabs_view_config",
        lambda: AgentTabsViewConfig(
            machine_mode=True,
            machine_order=(),
            pinned_by_alias={},
            named_order={},
            local_machine_name="athena",
            token=("prompt-context-test",),
        ),
    )
    mixin = PromptInputBarDispatchMixin.__new__(PromptInputBarDispatchMixin)
    mixin._dispatch_target_rows = {}
    segment = PromptInputBarDispatchMixin._named_tab_segment(
        mixin, "Athena", inherited=False
    )
    assert "named tab wins over ⌂ athena" in segment.plain
