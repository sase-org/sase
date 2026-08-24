"""Option-list building, highlight state, and description updates for
`ProviderRoutingModal`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.widgets import OptionList, Static
from textual.widgets._option_list import Option

from sase.llm_provider import ProviderRoutingStatus

from .models_panel_provider_rendering import (
    provider_description_text,
    render_provider_row,
)
from .models_panel_provider_state import ProviderRoutingSnapshot

if TYPE_CHECKING:
    from textual.screen import ModalScreen as _MixinBase
else:
    _MixinBase = object


class ProviderRoutingOptionsMixin(_MixinBase):
    """Build provider option rows and track highlight/description state."""

    if TYPE_CHECKING:
        _snapshot: ProviderRoutingSnapshot
        _statuses_by_provider: dict[str, ProviderRoutingStatus]
        _updating_highlight: bool

        def _now(self) -> float: ...

        def action_disable_or_change(self) -> None: ...

    def _build_options(self) -> list[Option]:
        statuses = self._snapshot.visible_statuses
        self._statuses_by_provider = {status.provider: status for status in statuses}
        if not statuses:
            return [
                Option(
                    Text("No user-facing LLM providers are registered.", style="dim"),
                    id="__empty__",
                    disabled=True,
                )
            ]
        now = self._now()
        return [
            Option(
                render_provider_row(
                    status,
                    colors=self._snapshot.provider_colors,
                    now=now,
                ),
                id=status.provider,
            )
            for status in statuses
        ]

    @staticmethod
    def _option_is_disabled(option_list: OptionList, index: int) -> bool:
        try:
            return option_list.get_option_at_index(index).disabled
        except Exception:
            return True

    @classmethod
    def _first_enabled_option_index(cls, option_list: OptionList) -> int | None:
        for index in range(option_list.option_count):
            if not cls._option_is_disabled(option_list, index):
                return index
        return None

    def _set_highlighted_index(
        self,
        option_list: OptionList,
        index: int | None,
    ) -> None:
        self._updating_highlight = True
        try:
            option_list.highlighted = index
        finally:
            self._updating_highlight = False

    def _restore_highlight(
        self,
        option_list: OptionList,
        preferred: str | None,
    ) -> None:
        if preferred is not None:
            try:
                index = option_list.get_option_index(preferred)
                if not self._option_is_disabled(option_list, index):
                    self._set_highlighted_index(option_list, index)
                    return
            except Exception:
                pass
        self._set_highlighted_index(
            option_list,
            self._first_enabled_option_index(option_list),
        )

    def _highlighted_provider(self) -> str | None:
        option_list = self.query_one("#provider-routing-list", OptionList)  # type: ignore[attr-defined]
        highlighted = option_list.highlighted
        if highlighted is None:
            return None
        try:
            option = option_list.get_option_at_index(highlighted)
        except Exception:
            return None
        provider = str(option.id) if option.id is not None else ""
        return provider if provider in self._statuses_by_provider else None

    def _selected_status(self) -> ProviderRoutingStatus | None:
        provider = self._highlighted_provider()
        if provider is None:
            return None
        return self._statuses_by_provider.get(provider)

    def _update_description(self) -> None:
        try:
            description = self.query_one("#provider-routing-description", Static)  # type: ignore[attr-defined]
        except Exception:
            return
        description.update(
            provider_description_text(self._selected_status(), now=self._now())
        )

    def on_option_list_option_highlighted(
        self,
        event: OptionList.OptionHighlighted,
    ) -> None:
        if self._updating_highlight:
            return
        self._update_description()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.action_disable_or_change()
