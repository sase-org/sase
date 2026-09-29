"""Shared helpers for the split model-alias completion tests.

The tests formerly lived in a single ``test_model_alias_completion`` module.
Helpers shared by more than one split module live here under public names;
the ``test_model_alias_completion_*`` modules import only these public names
(never ``_``-prefixed names from each other).
"""

from __future__ import annotations

from textual.app import ComposeResult

from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.xprompt.model_completion import ModelCompletionEntry

from ._completion_helpers import CompletionTestApp

__all__ = [
    "ColdModelAliasCompletionTestApp",
    "ModelAliasCompletionTestApp",
    "alias_entries",
]


class _DefaultEntries:
    pass


_USE_DEFAULT = _DefaultEntries()


class ModelAliasCompletionTestApp(CompletionTestApp):
    """Completion test app with a deterministic model catalog hook."""

    def __init__(
        self,
        *,
        entries: tuple[ModelCompletionEntry, ...] | None | _DefaultEntries = (
            _USE_DEFAULT
        ),
        settings: PromptCompletionSettings | None = None,
        available: bool = True,
        initial_panes: list[str] | None = None,
    ) -> None:
        super().__init__()
        self.entries: tuple[ModelCompletionEntry, ...] | None = (
            alias_entries() if isinstance(entries, _DefaultEntries) else entries
        )
        self.settings = settings or PromptCompletionSettings()
        self.available = available
        self.initial_panes = initial_panes
        self.submitted: list[str] = []

    def compose(self) -> ComposeResult:
        if self.initial_panes is None:
            yield PromptInputBar()
            return
        yield PromptInputBar(initial_panes=self.initial_panes)

    def get_prompt_completion_settings(self) -> PromptCompletionSettings:
        return self.settings

    def model_completion_catalog(
        self,
    ) -> tuple[tuple[ModelCompletionEntry, ...] | None, bool]:
        return self.entries, self.available

    def on_prompt_input_bar_submitted(
        self,
        message: PromptInputBar.Submitted,
    ) -> None:
        self.submitted.append(message.value)


class ColdModelAliasCompletionTestApp(CompletionTestApp):
    """Completion app without a synchronous model catalog provider."""

    def __init__(
        self,
        *,
        settings: PromptCompletionSettings | None = None,
        initial_panes: list[str] | None = None,
    ) -> None:
        super().__init__()
        self.settings = settings or PromptCompletionSettings()
        self.initial_panes = initial_panes
        self.submitted: list[str] = []

    def compose(self) -> ComposeResult:
        if self.initial_panes is None:
            yield PromptInputBar()
            return
        yield PromptInputBar(initial_panes=self.initial_panes)

    def get_prompt_completion_settings(self) -> PromptCompletionSettings:
        return self.settings

    def on_prompt_input_bar_submitted(
        self,
        message: PromptInputBar.Submitted,
    ) -> None:
        self.submitted.append(message.value)


def alias_entries() -> tuple[ModelCompletionEntry, ...]:
    return (
        ModelCompletionEntry(
            value="@large",
            display="@large",
            description="Large model",
            kind="user_alias",
            alias_kind="user",
            target_provider="codex",
            target_model="gpt-5",
            provenance="configured",
        ),
        ModelCompletionEntry(
            value="@small",
            display="@small",
            kind="implicit_alias",
            alias_kind="role",
            target_provider="codex",
            target_model="gpt-5-mini",
            provenance="implicit",
        ),
        ModelCompletionEntry(
            value="large-model",
            display="large-model",
            description="Concrete model",
            kind="model",
            provider="codex",
            provider_display="Codex",
            aliases=("large-model",),
        ),
    )
