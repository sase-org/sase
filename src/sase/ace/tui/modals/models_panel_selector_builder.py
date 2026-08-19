"""Guided pool / fallback selector builder for the Models panel Edit flow.

Assembles a round-robin pool or ordered fallback chain from the existing
model picker and effort ladder, so authoring a selector never requires typing
``|`` / ``||`` by hand. This is presentation-only glue: parsing, composition,
and validation all delegate to :mod:`sase.llm_provider.load_balancing` and
:mod:`sase.llm_provider.model_alias_resolution` — no selector semantics live
here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets._option_list import Option

from sase.ace.tui.model_alias_styles import append_effort_suffix, append_pool_weight
from sase.ace.tui.provider_styles import provider_model_badge_markup
from sase.llm_provider import (
    AliasView,
    EffectiveDefaultEffortSnapshot,
    TemporaryProviderDisable,
)
from sase.llm_provider.config import (
    normalize_model_alias_reference,
    validate_model_alias_selector_value,
)
from sase.llm_provider.load_balancing import (
    MAX_POOL_MEMBER_WEIGHT,
    MemberAvailability,
    ModelAliasSelectorError,
    ModelAliasSelectorMode,
    parse_model_alias_selector,
)
from sase.llm_provider.model_alias_resolution import (
    resolved_target_availability,
    resolved_target_is_available,
)
from sase.xprompt.effort import split_model_effort

from .base import OptionListNavigationMixin
from .custom_model_input_modal import CustomModelInputModal
from .model_picker_modal import CUSTOM_SENTINEL, AliasSelectionContext, ModelPickerModal
from .models_panel_effort_cards import DefaultEffortLevelChoice, DefaultEffortLevelModal
from .models_panel_provider_state import (
    disabled_explicit_provider_message,
    soft_explicit_provider_note,
)
from .models_panel_selector import (
    compose_selector,
    member_rejection,
    parse_selector_for_display,
)

_MODE_LABELS: dict[ModelAliasSelectorMode, str] = {
    "round_robin": "round-robin pool",
    "fallback": "ordered fallback",
}
_AVAILABLE_STYLE = "#87D787"
_UNAVAILABLE_STYLE = "#D78787"
_SOFT_STYLE = "bold #FFD75F"
_INVALID_STYLE = "bold #FF875F"
_KEYS_HINT = (
    "a=add  f=fallback  d=remove  J/K=reorder  E=effort  w/W=weight  "
    "t=toggle mode  enter=confirm  esc=cancel"
)
_MIN_MEMBERS = 2


def _seed_selector(
    value: str,
) -> tuple[ModelAliasSelectorMode, list[str], list[int], list[str]]:
    """Return the initial mode, pool members, weights, and last-resort tail."""
    try:
        selector = parse_model_alias_selector(value)
    except ModelAliasSelectorError:
        selector = None
    if selector is not None:
        return (
            selector.mode,
            list(selector.members),
            list(selector.weights),
            list(selector.fallback_members),
        )
    cleaned = value.strip()
    members = [cleaned] if cleaned else []
    return "round_robin", members, [1] * len(members), []


def _resolved_target_text(
    member: str, views_by_name: dict[str, AliasView]
) -> str | None:
    """Return a concrete ``provider/model`` (or bare model) string for *member*."""
    cleaned = member.strip()
    if not cleaned:
        return None
    if not cleaned.startswith("@"):
        return cleaned
    alias, _ = normalize_model_alias_reference(cleaned)
    view = views_by_name.get(alias) if alias else None
    if view is None:
        return None
    return f"{view.provider}/{view.model}" if view.provider else view.model


def _member_option(
    index: int,
    member: str,
    views_by_name: dict[str, AliasView],
    provider_disables: Mapping[str, TemporaryProviderDisable],
    weight: int = 1,
    *,
    last_resort: bool = False,
    display_index: int | None = None,
) -> Option:
    """Render one member row: position, provider/model badge, effort, availability."""
    raw_target, effort = split_model_effort(member)
    resolved_target = _resolved_target_text(raw_target, views_by_name)
    text = Text()
    if last_resort:
        text.append("fallback ", style="dim #AF87FF")
    shown = index if display_index is None else display_index
    text.append(f"{shown + 1}. ", style="bold #5FD7D7")
    if resolved_target is not None:
        text.append_text(
            Text.from_markup(provider_model_badge_markup(None, resolved_target))
        )
        available = resolved_target_is_available(
            resolved_target,
            provider_disables=provider_disables,
        )
        state = resolved_target_availability(
            resolved_target,
            provider_disables=provider_disables,
            available=available,
        )
        text.append("  ")
        if state is MemberAvailability.UNAVAILABLE:
            text.append("×", style=_UNAVAILABLE_STYLE)
        else:
            text.append("✓", style=_AVAILABLE_STYLE)
            if state is MemberAvailability.SPARING:
                text.append(" soft", style=_SOFT_STYLE)
    else:
        text.append(member, style=_INVALID_STYLE)
    append_effort_suffix(text, effort or "")
    append_pool_weight(text, weight)
    return Option(text, id=f"__member_{index}__")


class SelectorBuilderModal(OptionListNavigationMixin, ModalScreen[str | None]):
    """Assemble a pool/fallback selector from the picker and effort ladder."""

    _option_list_id = "selector-builder-list"

    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        Binding("a", "add_member", "Add", show=False),
        Binding("f", "add_fallback", "Fallback", show=False),
        Binding("d", "remove_member", "Remove", show=False),
        Binding("J", "move_down", "Move down", show=False),
        Binding("K", "move_up", "Move up", show=False),
        Binding("E", "edit_effort", "Effort", show=False),
        Binding("w", "increase_weight", "Weight+", show=False),
        Binding("W", "decrease_weight", "Weight-", show=False),
        Binding("t", "toggle_mode", "Toggle mode", show=False),
        Binding("enter", "confirm", "Confirm", show=False),
    ]

    def __init__(
        self,
        *,
        alias: str,
        current_value: str,
        alias_context: AliasSelectionContext,
        effort_snapshot: EffectiveDefaultEffortSnapshot,
        now: float,
        provider_disables: Mapping[str, TemporaryProviderDisable] | None = None,
    ) -> None:
        super().__init__()
        self._alias = alias
        self._alias_context = alias_context
        self._member_context = replace(alias_context, operation="member")
        self._effort_snapshot = effort_snapshot
        self._now = now
        self._provider_disables = dict(provider_disables or {})
        self._views_by_name = {view.name: view for view in alias_context.views}
        mode, members, weights, fallback_members = _seed_selector(current_value)
        self._mode: ModelAliasSelectorMode = mode
        self._members = members
        self._weights = weights
        self._fallback_members = fallback_members
        self._pending_member = ""
        self._pending_effort_index: int | None = None
        self._pending_target: str = "pool"

    # -- compose ----------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Container(id="selector-builder-container"):
            yield Static(self._header_text(), id="selector-builder-header")
            yield OptionList(*self._render_options(), id=self._option_list_id)
            yield Static(self._validation_text(), id="selector-builder-validation")
            yield Static(_KEYS_HINT, id="selector-builder-footer")

    def on_mount(self) -> None:
        self.query_one(f"#{self._option_list_id}", OptionList).focus()

    # -- rendering ----------------------------------------------------------

    def _header_text(self) -> Text:
        text = Text()
        text.append(f"@{self._alias}  ", style="bold")
        text.append(_MODE_LABELS[self._mode], style="bold #AF87FF")
        text.append("\n")
        if self._members or self._fallback_members:
            text.append(
                compose_selector(
                    self._mode,
                    self._members,
                    self._weights,
                    self._fallback_members,
                ),
                style="dim",
            )
        else:
            text.append("(no members yet)", style="dim")
        return text

    def _row_count(self) -> int:
        return len(self._members) + len(self._fallback_members)

    def _render_options(self) -> list[Option]:
        if not self._row_count():
            return [
                Option(
                    Text("  (no members yet — press a to add one)", style="dim"),
                    id="__empty__",
                    disabled=True,
                )
            ]
        options = [
            _member_option(
                index,
                member,
                self._views_by_name,
                self._provider_disables,
                self._weights[index],
            )
            for index, member in enumerate(self._members)
        ]
        options.extend(
            _member_option(
                len(self._members) + index,
                member,
                self._views_by_name,
                self._provider_disables,
                last_resort=True,
                display_index=index,
            )
            for index, member in enumerate(self._fallback_members)
        )
        return options

    def _validation_errors(self) -> tuple[str, ...]:
        if len(self._members) < _MIN_MEMBERS:
            return ()
        expression = compose_selector(
            self._mode,
            self._members,
            self._weights,
            self._fallback_members,
        )
        return validate_model_alias_selector_value(self._alias, expression)

    def _validation_text(self) -> Text:
        if len(self._members) < _MIN_MEMBERS:
            missing = _MIN_MEMBERS - len(self._members)
            noun = "member" if missing == 1 else "members"
            return Text(f"Add {missing} more {noun} to confirm", style="bold #FFD75F")
        errors = self._validation_errors()
        if errors:
            text = Text()
            for index, error in enumerate(errors):
                if index:
                    text.append("\n")
                text.append(f"✗ {error}", style=_INVALID_STYLE)
            return text
        return Text("✓ ready to confirm", style="bold #87D787")

    def _refresh_view(self, *, preferred_index: int | None = None) -> None:
        self.query_one("#selector-builder-header", Static).update(self._header_text())
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        option_list.clear_options()
        option_list.add_options(self._render_options())
        if self._row_count():
            index = 0 if preferred_index is None else preferred_index
            index = max(0, min(index, self._row_count() - 1))
            option_list.highlighted = index
        self.query_one("#selector-builder-validation", Static).update(
            self._validation_text()
        )

    def _highlighted_index(self) -> int | None:
        if not self._row_count():
            return None
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        return option_list.highlighted

    def _is_pool_index(self, index: int) -> bool:
        return 0 <= index < len(self._members)

    # -- add member -----------------------------------------------------

    def action_add_member(self) -> None:
        self._pending_target = "pool"
        self._open_member_picker(f"Add Member — @{self._alias}")

    def action_add_fallback(self) -> None:
        if self._mode != "round_robin":
            self.notify(
                "Last-resort candidates require a round-robin pool.",
                severity="warning",
            )
            return
        self._pending_target = "fallback"
        self._open_member_picker(f"Add Last-Resort — @{self._alias}")

    def _open_member_picker(self, title: str) -> None:
        self.app.push_screen(
            ModelPickerModal(
                title=title,
                include_default_option=False,
                alias_context=self._member_context,
                provider_disables=self._provider_disables,
            ),
            callback=self._on_member_picked,
        )

    def _on_member_picked(self, result: str | None) -> None:
        if result is None:
            return
        if result == CUSTOM_SENTINEL:
            self.app.push_screen(
                CustomModelInputModal(
                    title="Custom Member",
                    hint=(
                        "Format: model, provider/model, or @alias; "
                        "optional trailing @effort"
                    ),
                    placeholder="e.g. codex/gpt-5.6-sol@medium",
                ),
                callback=self._on_member_custom_picked,
            )
            return
        rejection = member_rejection(self._member_context, result)
        if rejection is not None:
            self.notify(
                f"Cannot add {result.strip()}: {rejection}.", severity="warning"
            )
            return
        self._open_member_effort_picker(result)

    def _on_member_custom_picked(self, result: str | None) -> None:
        if result is None:
            return
        raw = result.strip()
        parsed = parse_selector_for_display(raw)
        if parsed.error is not None:
            self.notify(parsed.error, severity="warning")
            return
        if parsed.selector is not None:
            self.notify(
                "Cannot add selector expression: a builder member must be a "
                "single target.",
                severity="warning",
            )
            return
        rejection = member_rejection(self._member_context, raw)
        if rejection is not None:
            self.notify(f"Cannot add {raw}: {rejection}.", severity="warning")
            return
        disabled = disabled_explicit_provider_message(
            raw,
            self._provider_disables,
            now=self._now,
        )
        if disabled is not None:
            self.notify(f"Cannot add {raw}: {disabled}.", severity="warning")
            return
        note = soft_explicit_provider_note(
            raw,
            self._provider_disables,
            now=self._now,
        )
        if note is not None:
            self.notify(note)
        _, effort = split_model_effort(raw)
        if effort is not None:
            self._append_member(raw)
            return
        self._open_member_effort_picker(raw)

    def _open_member_effort_picker(self, raw_member: str) -> None:
        self._pending_member = raw_member.strip()
        self.app.push_screen(
            DefaultEffortLevelModal(
                "model",
                self._effort_snapshot,
                now=self._now,
                model=self._pending_member,
            ),
            callback=self._on_member_effort_picked,
        )

    def _on_member_effort_picked(self, result: DefaultEffortLevelChoice | None) -> None:
        if result is None:
            return
        member = self._pending_member
        if result.effort is not None:
            member = f"{member}@{result.effort}"
        self._append_member(member)

    def _append_member(self, member: str) -> None:
        if self._pending_target == "fallback":
            self._fallback_members.append(member)
            self._refresh_view(preferred_index=self._row_count() - 1)
            return
        self._members.append(member)
        self._weights.append(1)
        self._refresh_view(preferred_index=len(self._members) - 1)

    # -- remove / reorder -------------------------------------------------

    def action_remove_member(self) -> None:
        index = self._highlighted_index()
        if index is None:
            return
        if self._is_pool_index(index):
            del self._members[index]
            del self._weights[index]
        else:
            del self._fallback_members[index - len(self._members)]
        self._refresh_view(preferred_index=index)

    def action_move_down(self) -> None:
        self._reorder(1)

    def action_move_up(self) -> None:
        self._reorder(-1)

    def _reorder(self, delta: int) -> None:
        index = self._highlighted_index()
        if index is None:
            return
        target = index + delta
        if not (0 <= target < self._row_count()):
            return
        if self._is_pool_index(index) != self._is_pool_index(target):
            return
        if self._is_pool_index(index):
            self._members[index], self._members[target] = (
                self._members[target],
                self._members[index],
            )
            self._weights[index], self._weights[target] = (
                self._weights[target],
                self._weights[index],
            )
        else:
            local = index - len(self._members)
            local_target = target - len(self._members)
            self._fallback_members[local], self._fallback_members[local_target] = (
                self._fallback_members[local_target],
                self._fallback_members[local],
            )
        self._refresh_view(preferred_index=target)

    # -- effort -------------------------------------------------------------

    def action_edit_effort(self) -> None:
        index = self._highlighted_index()
        if index is None:
            return
        self._pending_effort_index = index
        target, _ = split_model_effort(self._row_member(index))
        self.app.push_screen(
            DefaultEffortLevelModal(
                "model",
                self._effort_snapshot,
                now=self._now,
                model=target,
            ),
            callback=self._on_member_effort_edited,
        )

    def _row_member(self, index: int) -> str:
        if self._is_pool_index(index):
            return self._members[index]
        return self._fallback_members[index - len(self._members)]

    def _set_row_member(self, index: int, member: str) -> None:
        if self._is_pool_index(index):
            self._members[index] = member
            return
        self._fallback_members[index - len(self._members)] = member

    def _on_member_effort_edited(self, result: DefaultEffortLevelChoice | None) -> None:
        if result is None:
            return
        index = self._pending_effort_index
        self._pending_effort_index = None
        if index is None or not (0 <= index < self._row_count()):
            return
        target, _ = split_model_effort(self._row_member(index))
        self._set_row_member(
            index, f"{target}@{result.effort}" if result.effort else target
        )
        self._refresh_view(preferred_index=index)

    # -- mode / confirm -------------------------------------------------

    def action_increase_weight(self) -> None:
        self._nudge_weight(1)

    def action_decrease_weight(self) -> None:
        self._nudge_weight(-1)

    def _nudge_weight(self, delta: int) -> None:
        if self._mode != "round_robin":
            return
        index = self._highlighted_index()
        if index is None or not self._is_pool_index(index):
            return
        self._weights[index] = max(
            1,
            min(MAX_POOL_MEMBER_WEIGHT, self._weights[index] + delta),
        )
        self._refresh_view(preferred_index=index)

    def action_toggle_mode(self) -> None:
        if self._fallback_members:
            self.notify(
                "Cannot toggle pool/fallback while a last-resort tail is "
                "present; remove fallback rows first.",
                severity="warning",
            )
            return
        if self._mode == "round_robin":
            dropped = any(weight > 1 for weight in self._weights)
            self._mode = "fallback"
            if dropped:
                self._weights = [1] * len(self._weights)
                self.notify(
                    "Weights were cleared because ordered fallback cannot "
                    "weight candidates."
                )
        else:
            self._mode = "round_robin"
        self._refresh_view(preferred_index=self._highlighted_index())

    def action_confirm(self) -> None:
        if len(self._members) < _MIN_MEMBERS or self._validation_errors():
            return
        self.dismiss(
            compose_selector(
                self._mode,
                self._members,
                self._weights,
                self._fallback_members,
            )
        )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.action_confirm()


__all__ = ["SelectorBuilderModal"]
