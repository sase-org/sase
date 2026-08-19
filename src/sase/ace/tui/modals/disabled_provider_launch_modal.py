"""Single-keypress ACE panel for a launch unit blocked by a hard disable."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from rich.cells import cell_len
from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Static

from sase.ace.tui.modals.models_panel_provider_state import remaining_label
from sase.ace.tui.provider_disable_display import provider_disable_provenance_label
from sase.agent.launch_guard import (
    LaunchUnit,
    LaunchUnitCandidate,
    launch_unit_block_reason,
)
from sase.llm_provider.provider_disable import TemporaryProviderDisable
from sase.llm_provider.provider_disable_peek import peek_active_provider_disables

_DISABLED_STYLE = "#FFAF5F"
_PROMPT_PREVIEW_WIDTH = 64

type DisabledProviderLaunchAction = Literal[
    "enable",
    "soft_enable",
    "enable_provider",
    "pick_model",
    "abort_unit",
    "abort_all",
]


@dataclass(frozen=True)
class DisabledProviderLaunchDecision:
    """One keypress from the disabled-provider launch panel."""

    action: DisabledProviderLaunchAction
    provider: str | None = None


@dataclass(frozen=True)
class _DisabledProviderLaunchRow:
    """One selectable (or dim informational) row in the panel."""

    key: str
    title: str
    subtitle: str = ""
    result: DisabledProviderLaunchDecision | None = None
    tone: str = ""


def _take_cells(value: str, width: int, *, from_right: bool = False) -> str:
    if width <= 0:
        return ""
    chars = reversed(value) if from_right else iter(value)
    used = 0
    taken: list[str] = []
    for char in chars:
        char_width = max(cell_len(char), 0)
        if used + char_width > width:
            break
        taken.append(char)
        used += char_width
    if from_right:
        taken.reverse()
    return "".join(taken)


def _middle_elide_cells(value: str, width: int) -> str:
    if width <= 0:
        return ""
    value = " ".join(value.splitlines())
    if cell_len(value) <= width:
        return value
    if width == 1:
        return "…"
    left_width = max(1, (width - 1) // 2)
    right_width = max(0, width - 1 - left_width)
    suffix = _take_cells(value, right_width, from_right=True)
    return f"{_take_cells(value, left_width)}…{suffix}"


def _join_provider_names(providers: Sequence[str]) -> str:
    labels = [name.upper() for name in providers if name]
    if not labels:
        return "the provider"
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} and {labels[1]}"
    return f"{', '.join(labels[:-1])}, and {labels[-1]}"


def _blocked_candidate(unit: LaunchUnit) -> LaunchUnitCandidate | None:
    for candidate in unit.candidates:
        if candidate.blocked_by is not None:
            return candidate
    return unit.candidates[0] if unit.candidates else None


def _unavailable_note(
    unit: LaunchUnit,
    *,
    snapshot: Mapping[str, TemporaryProviderDisable] | None = None,
) -> str | None:
    """Return CLI-missing pool context when that is part of the block story."""
    candidate = _blocked_candidate(unit)
    if candidate is None:
        return None
    from sase.llm_provider.model_alias_resolution import model_alias_selector_details
    from sase.xprompt.directives import extract_prompt_directives

    _cleaned, directives = extract_prompt_directives(candidate.prompt)
    alias = directives.model_alias
    if not alias:
        return None
    details = model_alias_selector_details(alias, provider_disables=snapshot)
    if details is None or not details.members:
        return None
    blocked = set(unit.blocking_providers)
    unavailable = [
        member
        for member in details.members
        if not member.available and member.provider not in blocked
    ]
    if not unavailable:
        return None
    total = len(details.members)
    return f"{len(unavailable)} of {total} pool members are unavailable"


def _disable_records(
    unit: LaunchUnit,
    snapshot: Mapping[str, TemporaryProviderDisable],
) -> tuple[TemporaryProviderDisable, ...]:
    found: list[TemporaryProviderDisable] = []
    seen: set[str] = set()
    for name in unit.blocking_providers:
        record = snapshot.get(name)
        if record is None:
            continue
        if name in seen:
            continue
        seen.add(name)
        found.append(record)
    if found:
        return tuple(found)
    for candidate in unit.candidates:
        record = candidate.blocked_by
        if record is None or record.provider in seen:
            continue
        seen.add(record.provider)
        found.append(record)
    return tuple(found)


def _choice_rows(
    unit: LaunchUnit,
    *,
    original_total: int | None = None,
) -> list[_DisabledProviderLaunchRow]:
    """Return the keypress rows for *unit*, including dim informational lines."""
    total = original_total if original_total is not None else unit.total
    providers = unit.blocking_providers
    names = _join_provider_names(providers)
    rows: list[_DisabledProviderLaunchRow] = [
        _DisabledProviderLaunchRow(
            "e",
            f"Enable {names}, then launch this agent",
            "Clears the disable for every later launch too.",
            DisabledProviderLaunchDecision(action="enable"),
            tone="primary",
        ),
        _DisabledProviderLaunchRow(
            "s",
            f"Soft-enable {names}, then launch this agent",
            "Keeps sparing it in pools; this agent still runs on it.",
            DisabledProviderLaunchDecision(action="soft_enable"),
            tone="accent",
        ),
    ]
    if len(providers) >= 2:
        for index, provider in enumerate(providers[:9], start=1):
            rows.append(
                _DisabledProviderLaunchRow(
                    str(index),
                    f"Enable {provider.upper()} only, then re-check",
                    result=DisabledProviderLaunchDecision(
                        action="enable_provider",
                        provider=provider,
                    ),
                )
            )
    if unit.single_model is not None:
        rows.append(
            _DisabledProviderLaunchRow(
                "m",
                "Pick a different model for this agent…",
                result=DisabledProviderLaunchDecision(action="pick_model"),
            )
        )
    else:
        rows.append(
            _DisabledProviderLaunchRow(
                "",
                "This prompt fans out models; press esc and edit it to change a branch.",
            )
        )
    abort_subtitle = (
        f"The other {total - 1} agents in this launch still start."
        if total > 1
        else "This launch will not start."
    )
    rows.append(
        _DisabledProviderLaunchRow(
            "a",
            "Abort this agent",
            abort_subtitle,
            DisabledProviderLaunchDecision(action="abort_unit"),
        )
    )
    if total > 1:
        rows.append(
            _DisabledProviderLaunchRow(
                "A",
                f"Abort all {total} agents",
                result=DisabledProviderLaunchDecision(action="abort_all"),
                tone="accent",
            )
        )
    return rows


class DisabledProviderLaunchModal(ModalScreen[DisabledProviderLaunchDecision | None]):
    """Single-key chooser that resolves one blocked launch unit."""

    AUTO_FOCUS = ""

    BINDINGS = [
        Binding("e", "enable", "Enable", show=False),
        Binding("s", "soft_enable", "Soft-enable", show=False),
        *[
            Binding(str(index), f"enable_one('{index}')", f"Enable {index}", show=False)
            for index in range(1, 10)
        ],
        Binding("m", "pick_model", "Pick model", show=False),
        Binding("a", "abort_unit", "Abort this agent", show=False),
        Binding("A", "abort_all", "Abort all", show=False),
        Binding("escape", "abort_unit", "Abort this agent", show=False),
        Binding("q", "abort_unit", "Abort this agent", show=False),
    ]

    def __init__(
        self,
        unit: LaunchUnit,
        *,
        now: float,
        snapshot: Mapping[str, TemporaryProviderDisable] | None = None,
        original_total: int | None = None,
    ) -> None:
        super().__init__()
        self._unit = unit
        self._now = now
        self._snapshot = (
            dict(snapshot) if snapshot is not None else peek_active_provider_disables()
        )
        self._original_total = (
            original_total if original_total is not None else unit.total
        )
        self._rows = _choice_rows(unit, original_total=self._original_total)
        self._rows_by_key = {row.key: row for row in self._rows if row.key}

    def compose(self) -> ComposeResult:
        with Container(
            id="disabled-provider-launch-container",
            classes="duration-choice-container",
        ):
            with Vertical(
                id="disabled-provider-launch-body",
                classes="duration-choice-body",
            ):
                yield Label(
                    self._title_text(),
                    id="disabled-provider-launch-title",
                    classes="duration-choice-title",
                )
                for line in self._provider_lines():
                    yield Static(
                        line,
                        classes="disabled-provider-launch-status duration-choice-row",
                    )
                yield Static(
                    self._reason_text(),
                    classes="disabled-provider-launch-reason duration-choice-row",
                )
                yield Static(
                    self._prompt_preview(),
                    classes="disabled-provider-launch-preview duration-choice-row",
                )
                yield Static(
                    "",
                    classes="disabled-provider-launch-spacer duration-choice-spacer",
                )
                for row in self._rows:
                    yield Static(
                        self._render_row(row),
                        classes=self._row_classes(row),
                    )
                yield Static(
                    "",
                    classes="disabled-provider-launch-spacer duration-choice-spacer",
                )
                yield Static(
                    "  [dim]esc = abort this agent[/]",
                    classes="disabled-provider-launch-footer duration-choice-row",
                )

    def _title_text(self) -> str:
        if self._original_total > 1:
            return (
                f"Provider disabled · agent {self._unit.index} of "
                f"{self._original_total}"
            )
        return "Provider disabled"

    def _provider_lines(self) -> list[str]:
        lines: list[str] = []
        for record in _disable_records(self._unit, self._snapshot):
            provenance = provider_disable_provenance_label(record)
            remaining = remaining_label(record, now=self._now)
            state = "soft" if record.is_soft else "disabled"
            lines.append(
                f"  [bold {_DISABLED_STYLE}]{escape(record.provider.upper())}[/]"
                f"   {state} · {escape(provenance)} · {escape(remaining)}"
            )
        if lines:
            return lines
        names = _join_provider_names(self._unit.blocking_providers)
        return [f"  [bold {_DISABLED_STYLE}]{escape(names)}[/]   disabled"]

    def _reason_text(self) -> str:
        reason = launch_unit_block_reason(self._unit)
        note = _unavailable_note(self._unit, snapshot=self._snapshot)
        if note:
            reason = f"{reason} {note}."
        return f"  {escape(reason)}"

    def _prompt_preview(self) -> str:
        preview = _middle_elide_cells(self._unit.prompt, _PROMPT_PREVIEW_WIDTH)
        return f"  [dim]» {escape(preview)}[/]"

    @staticmethod
    def _render_row(row: _DisabledProviderLaunchRow) -> str:
        if not row.key:
            return f"  [dim]{escape(row.title)}[/]"
        line = f"  [bold]{row.key}[/]   [bold]{escape(row.title)}[/]"
        if row.subtitle:
            line = f"{line}\n      [dim]{escape(row.subtitle)}[/]"
        return line

    @staticmethod
    def _row_classes(row: _DisabledProviderLaunchRow) -> str:
        classes = "disabled-provider-launch-row duration-choice-row"
        if not row.key:
            return f"{classes} disabled-provider-launch-dim"
        if row.tone:
            classes = f"{classes} duration-choice-tone-{row.tone}"
        return classes

    def _dismiss_key(self, key: str) -> None:
        row = self._rows_by_key.get(key)
        if row is None or row.result is None:
            return
        self.dismiss(row.result)

    def action_enable(self) -> None:
        """Clear every provider blocking this unit, then re-check."""
        self._dismiss_key("e")

    def action_soft_enable(self) -> None:
        """Rewrite each blocking disable to soft, preserving its window."""
        self._dismiss_key("s")

    def action_enable_one(self, key: str) -> None:
        """Enable one blocking provider and re-check the unit."""
        self._dismiss_key(key)

    def action_pick_model(self) -> None:
        """Open the model picker for a single-model unit."""
        self._dismiss_key("m")

    def action_abort_unit(self) -> None:
        """Drop this agent and continue with the rest of the launch."""
        self._dismiss_key("a")

    def action_abort_all(self) -> None:
        """Cancel the whole launch and keep the prompt bar draft."""
        self._dismiss_key("A")


__all__ = [
    "DisabledProviderLaunchAction",
    "DisabledProviderLaunchDecision",
    "DisabledProviderLaunchModal",
]
