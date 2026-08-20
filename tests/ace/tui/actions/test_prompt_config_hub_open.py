"""Enabled-flag routing of prompt catalog shortcuts through Config Center."""

from __future__ import annotations

from sase.ace.tui.actions.agent_workflow._prompt_bar_glossary_panel import (
    PromptBarGlossaryPanelMixin,
)
from sase.ace.tui.actions.agent_workflow._prompt_bar_memory_panel import (
    PromptBarMemoryPanelMixin,
)
from sase.ace.tui.actions.agent_workflow._prompt_bar_snippets_panel import (
    PromptBarSnippetsPanelMixin,
)
from sase.ace.tui.modals.config_hub_session import ConfigHubEntry
from sase.ace.tui.modals.glossary_panel import GlossaryPanel
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.feature_flags import override_flags


class _HubOpenHarness(
    PromptBarGlossaryPanelMixin,
    PromptBarMemoryPanelMixin,
    PromptBarSnippetsPanelMixin,
):
    def __init__(self) -> None:
        self._prompt_context = None
        self.opened: list[tuple[object, dict[str, object]]] = []
        self.pushed: list[object] = []

    def _open_config_center(self, initial_tab: object, **kwargs: object) -> None:
        self.opened.append((initial_tab, kwargs))

    def push_screen(self, screen: object, callback: object = None) -> None:
        self.pushed.append(screen)

    def _mounted_prompt_bar(self) -> None:
        return None

    def _mounted_glossary_prompt_bar(self) -> None:
        return None

    def _mounted_memory_prompt_bar(self) -> None:
        return None

    def _mounted_snippet_prompt_bar(self) -> None:
        return None


def test_disabled_glossary_shortcut_still_opens_standalone_panel() -> None:
    harness = _HubOpenHarness()
    with override_flags(admin_center_config_hub=False):
        harness.on_prompt_input_bar_glossary_panel_requested(
            PromptInputBar.GlossaryPanelRequested("Agent Hood", "prompt")
        )

    assert harness.opened == []
    assert len(harness.pushed) == 1
    panel = harness.pushed[0]
    assert isinstance(panel, GlossaryPanel)
    assert panel._initial_term == "Agent Hood"


def test_enabled_glossary_shortcut_opens_config_hub_on_glossary() -> None:
    harness = _HubOpenHarness()
    with override_flags(admin_center_config_hub=True):
        harness.on_prompt_input_bar_glossary_panel_requested(
            PromptInputBar.GlossaryPanelRequested("Agent Hood", "prompt")
        )

    assert harness.pushed == []
    assert len(harness.opened) == 1
    tab, kwargs = harness.opened[0]
    assert tab == "config"
    entry = kwargs["config_entry"]
    assert isinstance(entry, ConfigHubEntry)
    assert entry.subtab == "glossary"
    assert entry.term == "Agent Hood"
    assert callable(kwargs["on_dismissed"])


def test_enabled_memory_shortcut_opens_config_hub_on_memory() -> None:
    harness = _HubOpenHarness()
    with override_flags(admin_center_config_hub=True):
        harness.on_prompt_input_bar_memory_panel_requested(
            PromptInputBar.MemoryPanelRequested("#memory/sase_beads", "prompt")
        )

    tab, kwargs = harness.opened[0]
    assert tab == "config"
    entry = kwargs["config_entry"]
    assert isinstance(entry, ConfigHubEntry)
    assert entry.subtab == "memory"
    assert entry.note is not None
    assert "sase_beads" in entry.note


def test_enabled_snippets_shortcut_opens_config_hub_on_snippets() -> None:
    harness = _HubOpenHarness()
    with override_flags(admin_center_config_hub=True):
        harness.on_prompt_input_bar_snippet_panel_requested(
            PromptInputBar.SnippetPanelRequested("todo", "prompt")
        )

    tab, kwargs = harness.opened[0]
    assert tab == "config"
    entry = kwargs["config_entry"]
    assert isinstance(entry, ConfigHubEntry)
    assert entry.subtab == "snippets"
    assert entry.trigger == "todo"
