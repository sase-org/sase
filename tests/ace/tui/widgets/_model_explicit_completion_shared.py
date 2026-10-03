"""Shared helpers for the split model-explicit completion tests.

The tests formerly lived in a single ``test_model_explicit_completion`` module.
Helpers shared by more than one split module live here under public names;
the ``test_model_explicit_completion_*`` modules import only these public names
(never ``_``-prefixed names from each other).
"""

from __future__ import annotations

from textual.app import ComposeResult

from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.macro.model_completion import ModelCompletionEntry

from ._completion_helpers import CompletionTestApp

__all__ = [
    "ColdModelExplicitCompletionTestApp",
    "ModelExplicitCompletionTestApp",
    "explicit_entries",
]


class _DefaultEntries:
    pass


_USE_DEFAULT = _DefaultEntries()


class ModelExplicitCompletionTestApp(CompletionTestApp):
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
            explicit_entries() if isinstance(entries, _DefaultEntries) else entries
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


class ColdModelExplicitCompletionTestApp(CompletionTestApp):
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


def explicit_entries() -> tuple[ModelCompletionEntry, ...]:
    return (
        ModelCompletionEntry(
            value="@large",
            display="@large",
            description="Large alias",
            kind="user_alias",
            alias_kind="user",
            aliases=("large",),
            target_provider="codex",
            target_model="gpt-5.6-sol",
            provenance="configured",
        ),
        ModelCompletionEntry(
            value="gpt-5.6-sol",
            display="gpt-5.6-sol",
            description="Codex (sol)",
            kind="model",
            provider="codex",
            provider_display="Codex",
            aliases=("sol", "gpt56sol"),
        ),
        ModelCompletionEntry(
            value="claude-fable-5",
            display="claude-fable-5",
            description="Claude (fable)",
            kind="model",
            provider="claude",
            provider_display="Claude",
            aliases=("fable",),
        ),
        ModelCompletionEntry(
            value="codex/",
            display="codex/",
            description="Codex",
            kind="provider",
            provider="codex",
            provider_display="Codex",
            provider_model_count=1,
        ),
        ModelCompletionEntry(
            value="opencode/",
            display="opencode/",
            description="OpenCode",
            kind="provider",
            provider="opencode",
            provider_display="OpenCode",
            provider_model_count=1,
        ),
        ModelCompletionEntry(
            value="anthropic/claude-sonnet-4-5",
            display="anthropic/claude-sonnet-4-5",
            description="OpenCode Anthropic",
            kind="model",
            provider="opencode",
            provider_display="OpenCode Anthropic",
        ),
    )
