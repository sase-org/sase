"""Single-keypress ACE panel for draining a manually disabled provider."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Literal

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Static

from sase.ace.tui.modals.models_panel_provider_state import remaining_label
from sase.ace.tui.provider_disable_display import provider_disable_provenance_label
from sase.agent.provider_drain import ProviderDrainPlan, ProviderDrainSkip

_DRAIN_STYLE = "#AF87FF"

type ProviderDrainPromptAction = Literal["relaunch", "pick_model", "leave"]


@dataclass(frozen=True)
class ProviderDrainPromptDecision:
    """One keypress from the provider-drain prompt panel."""

    action: ProviderDrainPromptAction


@dataclass(frozen=True)
class _ProviderDrainPromptRow:
    """One selectable row in the provider-drain prompt."""

    key: str
    title: str
    subtitle: str = ""
    result: ProviderDrainPromptDecision | None = None
    tone: str = ""


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    word = singular if count == 1 else plural or f"{singular}s"
    return f"{count} {word}"


def _route_summary(plan: ProviderDrainPlan) -> str:
    if not plan.moves:
        return "No agents can relaunch without a model override."
    counts = Counter(
        (move.route.target_provider or "unknown").upper() for move in plan.moves
    )
    routes = " / ".join(f"{count} to {provider}" for provider, count in counts.items())
    return f"{routes} / in-flight work is lost"


def _skip_summary(plan: ProviderDrainPlan) -> str:
    if not plan.skips:
        return "No dependent agents left alone."
    grouped: dict[str, list[ProviderDrainSkip]] = {}
    for skip in plan.skips:
        grouped.setdefault(skip.reason, []).append(skip)
    parts: list[str] = []
    for reason in sorted(grouped):
        rows = grouped[reason]
        if reason == "stranded":
            target = _stranded_target(rows[0])
            parts.append(f"{len(rows)} pinned to {target} cannot move either way")
        elif reason == "pending_question":
            parts.append(f"{len(rows)} waiting on a question")
        elif reason == "monitor":
            parts.append(f"{len(rows)} monitor row")
        elif reason == "caller":
            parts.append(f"{len(rows)} current agent")
        elif reason == "capped":
            parts.append(f"{len(rows)} over the drain limit")
        else:
            parts.append(f"{len(rows)} {reason.replace('_', ' ')}")
    return " / ".join(parts)


def _stranded_target(skip: ProviderDrainSkip) -> str:
    detail = skip.detail
    prefix = "pinned to "
    if detail.startswith(prefix):
        rest = detail[len(prefix) :]
        return rest.split(";", 1)[0].strip() or "that model"
    return "that model"


def _choice_rows(plan: ProviderDrainPlan) -> list[_ProviderDrainPromptRow]:
    rows: list[_ProviderDrainPromptRow] = []
    if plan.moves:
        rows.append(
            _ProviderDrainPromptRow(
                "r",
                f"Relaunch {_plural(len(plan.moves), 'agent')} now",
                _route_summary(plan),
                ProviderDrainPromptDecision(action="relaunch"),
                tone="primary",
            )
        )
    rows.extend(
        [
            _ProviderDrainPromptRow(
                "m",
                "Relaunch them on a model I pick...",
                "Uses the same provider/model spelling as agent drain --model.",
                ProviderDrainPromptDecision(action="pick_model"),
                tone="accent",
            ),
            _ProviderDrainPromptRow(
                "l",
                "Leave them alone",
                _skip_summary(plan),
                ProviderDrainPromptDecision(action="leave"),
            ),
        ]
    )
    return rows


class ProviderDrainPromptModal(ModalScreen[ProviderDrainPromptDecision]):
    """Single-key chooser for a provider drain after a manual hard disable."""

    AUTO_FOCUS = ""

    BINDINGS = [
        Binding("r", "relaunch", "Relaunch", show=False),
        Binding("m", "pick_model", "Pick model", show=False),
        Binding("l", "leave", "Leave alone", show=False),
        Binding("escape", "leave", "Leave alone", show=False),
        Binding("q", "leave", "Leave alone", show=False),
    ]

    def __init__(self, plan: ProviderDrainPlan, *, now: float) -> None:
        super().__init__()
        self._plan = plan
        self._now = now
        self._rows = _choice_rows(plan)
        self._rows_by_key = {row.key: row for row in self._rows}

    def compose(self) -> ComposeResult:
        with Container(
            id="provider-drain-prompt-container",
            classes="duration-choice-container",
        ):
            with Vertical(
                id="provider-drain-prompt-body",
                classes="duration-choice-body",
            ):
                yield Label(
                    self._title_text(),
                    id="provider-drain-prompt-title",
                    classes="duration-choice-title",
                )
                yield Static(
                    self._disable_line(),
                    classes="provider-drain-prompt-status duration-choice-row",
                )
                yield Static(
                    self._candidate_line(),
                    classes="provider-drain-prompt-status duration-choice-row",
                )
                yield Static(
                    "",
                    classes="provider-drain-prompt-spacer duration-choice-spacer",
                )
                for row in self._rows:
                    yield Static(
                        self._render_row(row),
                        classes=self._row_classes(row),
                    )
                yield Static(
                    "",
                    classes="provider-drain-prompt-spacer duration-choice-spacer",
                )
                yield Static(
                    "  [dim]esc/q/l = leave them alone[/]",
                    classes="provider-drain-prompt-footer duration-choice-row",
                )

    def _title_text(self) -> str:
        provider = self._plan.provider.upper()
        total = len(self._plan.moves) + len(self._plan.skips)
        noun = "agent depends" if total == 1 else "agents depend"
        return f"{provider} disabled / {total} {noun} on it"

    def _disable_line(self) -> str:
        disable = self._plan.disable
        return (
            f"  [bold {_DRAIN_STYLE}]{escape(disable.provider.upper())}[/]"
            f"   {escape(remaining_label(disable, now=self._now))}"
            f" / {escape(provider_disable_provenance_label(disable))}"
        )

    def _candidate_line(self) -> str:
        moves = (
            "1 can relaunch"
            if len(self._plan.moves) == 1
            else f"{len(self._plan.moves)} can relaunch"
        )
        skips = _plural(len(self._plan.skips), "left alone")
        return f"  {escape(moves)} / {escape(skips)}"

    @staticmethod
    def _render_row(row: _ProviderDrainPromptRow) -> str:
        line = f"  [bold]{row.key}[/]   [bold]{escape(row.title)}[/]"
        if row.subtitle:
            line = f"{line}\n      [dim]{escape(row.subtitle)}[/]"
        return line

    @staticmethod
    def _row_classes(row: _ProviderDrainPromptRow) -> str:
        classes = "provider-drain-prompt-row duration-choice-row"
        if row.tone:
            classes = f"{classes} duration-choice-tone-{row.tone}"
        return classes

    def _dismiss_key(self, key: str) -> None:
        row = self._rows_by_key.get(key)
        if row is None or row.result is None:
            return
        self.dismiss(row.result)

    def action_relaunch(self) -> None:
        """Submit the default drain."""
        self._dismiss_key("r")

    def action_pick_model(self) -> None:
        """Open a model picker before submitting the drain."""
        self._dismiss_key("m")

    def action_leave(self) -> None:
        """Leave dependent agents alone."""
        self._dismiss_key("l")


__all__ = [
    "ProviderDrainPromptAction",
    "ProviderDrainPromptDecision",
    "ProviderDrainPromptModal",
]
