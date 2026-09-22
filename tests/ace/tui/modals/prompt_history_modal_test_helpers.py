"""Shared helpers for prompt-history modal tests."""

from __future__ import annotations

from textual.app import App, ComposeResult

from sase.ace.tui.modals.prompt_history_modal import (
    _PromptDisplayItem,
    PromptHistoryModal,
)
from sase.core.prompt_history_filter_wire import PromptHistoryProjectIdentity
from sase.history.prompt_history_project_filter import (
    PromptHistoryProjectCatalog,
    prepare_prompt_history_row_facts,
)
from sase.history.prompt_store import PromptEntry


class _PromptHistoryTestApp(App[None]):
    """Minimal app harness for prompt-history modal pilot tests."""

    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


def _item(
    *,
    text: str = "fix the tests",
    context: str = "main",
    marker: str = " ",
    last_used: str = "260501_142530",
    cancelled: bool = False,
) -> _PromptDisplayItem:
    return _PromptDisplayItem(
        entry=PromptEntry(
            text=text,
            branch_or_workspace=context,
            timestamp="260501_140000",
            last_used=last_used,
            workspace="sase",
            cancelled=cancelled,
        ),
        marker=marker,
    )


def _catalog(*entries: PromptHistoryProjectIdentity) -> PromptHistoryProjectCatalog:
    return PromptHistoryProjectCatalog(entries=tuple(entries))


def _modal_with_catalog(
    catalog: PromptHistoryProjectCatalog,
    items: list[_PromptDisplayItem],
    *,
    show_cancelled: bool = False,
) -> PromptHistoryModal:
    modal = object.__new__(PromptHistoryModal)
    modal._catalog = catalog
    modal._all_items = items
    modal._show_cancelled = show_cancelled
    modal._row_facts = [
        prepare_prompt_history_row_facts(
            index, item.entry.text, _display_text_for_item(item), catalog
        )
        for index, item in enumerate(items)
    ]
    return modal


def _display_text_for_item(item: _PromptDisplayItem) -> str:
    return item.display_text if item.display_text is not None else item.entry.text


class _FakeScopeHint:
    """Fake ``Static`` recording updates/class toggles for hint assertions."""

    def __init__(self) -> None:
        self.value: object = None
        self.added: list[str] = []
        self.removed: list[str] = []

    def update(self, value: object) -> None:
        self.value = value

    def add_class(self, name: str) -> None:
        self.added.append(name)

    def remove_class(self, name: str) -> None:
        self.removed.append(name)


def _plain(value: object) -> str:
    return value.plain if hasattr(value, "plain") else str(value)
