"""Shared harnesses for prompt-bar xprompt and snippet save tests."""

from __future__ import annotations

import asyncio
from typing import Any

from textual.app import App, ComposeResult

from sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt import (
    PromptBarSaveXpromptMixin,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar


class _SaveHarness(PromptBarSaveXpromptMixin):
    def __init__(self) -> None:
        self._prompt_context = None
        self.notifications: list[tuple[str, str | None]] = []
        self.pushed: list[tuple[object, object]] = []
        self.git_offers: list[tuple[str, bool, str, str]] = []
        self._user_snippets: dict[str, str] = {}
        self._snippets_cache: dict[str, str] | None = None
        self._pending_snippet_saves: dict[str, str] = {}
        self._snippet_config_path = ""

    def notify(self, msg: str, *, severity: str | None = None) -> None:
        self.notifications.append((msg, severity))

    def push_screen(self, screen: object, callback: object = None) -> None:
        self.pushed.append((screen, callback))

    def _offer_git_commit(
        self,
        file_path: str,
        *,
        is_new: bool,
        xprompt_name: str,
        noun: str = "xprompt",
        commit_type: str = "xprompt",
    ) -> None:
        del commit_type
        self.git_offers.append((file_path, is_new, xprompt_name, noun))

    async def _offer_post_write_actions(
        self,
        target: Any,
        *,
        kind: object,
        is_new: bool,
        xprompt_name: str,
        noun: str = "xprompt",
        commit_type: str = "xprompt",
        refresh_config_on_success: bool = False,
    ) -> None:
        del kind, commit_type, refresh_config_on_success
        file_path = str(target.write_path)
        self.git_offers.append((file_path, is_new, xprompt_name, noun))


class _CommitHarness(PromptBarSaveXpromptMixin):
    def __init__(self) -> None:
        self._prompt_context = None
        self.notifications: list[tuple[str, str | None]] = []
        self.pushed: list[tuple[object, object]] = []
        self.submitted: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.config_refreshes: list[str] = []

    def notify(self, msg: str, *, severity: str | None = None) -> None:
        self.notifications.append((msg, severity))

    def push_screen(self, screen: object, callback: object = None) -> None:
        self.pushed.append((screen, callback))

    def _submit_tracked_task(self, *args: object, **kwargs: object) -> object:
        self.submitted.append((args, kwargs))
        return object()

    def _request_prompt_catalog_config_refresh(self, *, reason: str) -> None:
        self.config_refreshes.append(reason)


class _SaveFlowApp(PromptBarSaveXpromptMixin, App[None]):
    """Exercise prompt dispatch and the real async save-panel boundary."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(self, initial_value: str) -> None:
        super().__init__()
        self._initial_value = initial_value
        self._prompt_context = None
        self._user_snippets: dict[str, str] = {}
        self._snippets_cache: dict[str, str] | None = None
        self._pending_snippet_saves: dict[str, str] = {}
        self._snippet_config_path = ""
        self.save_requests: list[PromptInputBar.SaveAsXpromptRequested] = []

    def compose(self) -> ComposeResult:
        yield PromptInputBar(initial_value=self._initial_value)

    async def on_prompt_input_bar_save_as_xprompt_requested(
        self, event: PromptInputBar.SaveAsXpromptRequested
    ) -> None:
        self.save_requests.append(event)
        await super().on_prompt_input_bar_save_as_xprompt_requested(event)

    def _offer_git_commit(self, *_args: object, **_kwargs: object) -> None:
        pass

    async def _offer_post_write_actions(
        self, *_args: object, **_kwargs: object
    ) -> None:
        pass

    def get_snippets(self) -> dict[str, str]:
        return self._snippets_cache or self._user_snippets


async def _wait_save_tasks(harness: object) -> None:
    tasks = list(getattr(harness, "_xprompt_save_async_tasks", set()))
    if tasks:
        await asyncio.gather(*tasks)
