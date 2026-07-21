"""Single-key action and level cards for Models-panel default effort."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.llm_provider import EffectiveDefaultEffortSnapshot
from sase.xprompt.effort import EFFORT_LEVELS_ORDERED

from .models_panel_duration import format_remaining

type DefaultEffortAction = Literal["edit", "override", "clear"]
type DefaultEffortPickerMode = Literal["edit", "override"]


@dataclass(frozen=True)
class DefaultEffortLevelChoice:
    """Chosen canonical effort, or ``None`` for provider default."""

    effort: str | None


class DefaultEffortActionModal(ModalScreen[DefaultEffortAction | None]):
    """Compact one-key chooser for persistent or temporary effort changes."""

    BINDINGS = [
        Binding("e", "choose_edit", "Edit", show=False),
        Binding("o", "choose_override", "Override", show=False),
        Binding("x", "choose_clear", "Clear", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("q", "cancel", "Cancel", show=False),
    ]

    def __init__(
        self,
        snapshot: EffectiveDefaultEffortSnapshot,
        *,
        now: float,
        use_chezmoi: bool,
    ) -> None:
        super().__init__()
        self._snapshot = snapshot
        self._now = now
        self._use_chezmoi = use_chezmoi

    def compose(self) -> ComposeResult:
        with Container(id="default-effort-action-container"):
            yield Static("Default Effort", id="default-effort-action-title")
            yield Static(self._status_text(), id="default-effort-action-status")
            with Vertical(id="default-effort-action-choices"):
                target = "chezmoi source" if self._use_chezmoi else "user sase.yml"
                yield Static(
                    "  [bold]e[/]   Edit permanently\n"
                    f"      [dim]Write the {target} after a preview.[/]",
                    classes="default-effort-action-row",
                )
                yield Static(
                    "  [bold]o[/]   Override temporarily\n"
                    "      [dim]Leave configuration unchanged; choose a duration.[/]",
                    classes="default-effort-action-row",
                )
                if self._snapshot.active_override(self._now) is not None:
                    yield Static(
                        "  [bold]x[/]   Clear temporary override\n"
                        "      [dim]Resume the configured or provider default.[/]",
                        classes="default-effort-action-row",
                    )
            yield Static(
                "Explicit prompt effort and alias/member effort still win.\n"
                "Already-running agents are unaffected.",
                id="default-effort-action-note",
            )
            yield Static("esc / q: cancel", id="default-effort-action-footer")

    def _status_text(self) -> Text:
        text = Text("Current for new launches\n", style="bold")
        override = self._snapshot.active_override(self._now)
        if override is None:
            _append_effort(text, self._snapshot.configured_effort)
            return text
        _append_effort(text, override.effort)
        text.append("  ", style="dim")
        if override.expires_at is None:
            text.append("override · until cleared", style="bold #AF87FF")
        else:
            text.append(
                f"override · {format_remaining(override.expires_at - self._now)} left",
                style="bold #AF87FF",
            )
        text.append("\nConfigured: ", style="dim")
        _append_effort(text, self._snapshot.configured_effort)
        return text

    def action_choose_edit(self) -> None:
        self.dismiss("edit")

    def action_choose_override(self) -> None:
        self.dismiss("override")

    def action_choose_clear(self) -> None:
        if self._snapshot.active_override(self._now) is not None:
            self.dismiss("clear")

    def action_cancel(self) -> None:
        self.dismiss(None)


class DefaultEffortLevelModal(ModalScreen[DefaultEffortLevelChoice | None]):
    """Ordered single-key picker generated from the canonical vocabulary."""

    BINDINGS = [
        *[
            Binding(str(index), f"choose('{index}')", level, show=False)
            for index, level in enumerate(EFFORT_LEVELS_ORDERED, start=1)
        ],
        Binding("0", "choose('0')", "Provider default", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("q", "cancel", "Cancel", show=False),
    ]

    _TONES = (
        "#777777",
        "#8787AF",
        "#8787D7",
        "#AF87D7",
        "#AF87FF",
        "#D787FF",
        "#FF87FF",
    )

    def __init__(
        self,
        mode: DefaultEffortPickerMode,
        snapshot: EffectiveDefaultEffortSnapshot,
        *,
        now: float,
    ) -> None:
        super().__init__()
        self._mode = mode
        self._snapshot = snapshot
        self._now = now

    def compose(self) -> ComposeResult:
        with Container(id="default-effort-level-container"):
            yield Static("Default Effort Level", id="default-effort-level-title")
            subtitle = (
                "Choose the persistent launch default."
                if self._mode == "edit"
                else "Choose a temporary launch default."
            )
            yield Static(subtitle, id="default-effort-level-subtitle")
            with Vertical(id="default-effort-level-choices"):
                if self._mode == "edit":
                    yield Static(
                        self._row_text("0", None, "#777777"),
                        classes="default-effort-level-row",
                    )
                for index, (level, tone) in enumerate(
                    zip(EFFORT_LEVELS_ORDERED, self._TONES, strict=True),
                    start=1,
                ):
                    yield Static(
                        self._row_text(str(index), level, tone),
                        classes="default-effort-level-row",
                    )
            yield Static(
                "Config-derived levels are best-effort; providers that cannot "
                "honor one keep their provider behavior.",
                id="default-effort-level-note",
            )
            yield Static("esc / q: cancel", id="default-effort-level-footer")

    def _row_text(self, key: str, effort: str | None, tone: str) -> Text:
        label = effort or "provider default"
        text = Text("  ")
        text.append(key, style="bold")
        text.append("   ")
        text.append(label, style=f"bold {tone}")
        annotations = self._annotations(effort)
        if annotations:
            text.append("  ·  ", style="dim")
            text.append(" · ".join(annotations), style="dim")
        return text

    def _annotations(self, effort: str | None) -> list[str]:
        annotations: list[str] = []
        override = self._snapshot.active_override(self._now)
        configured = self._snapshot.configured_effort
        if configured == effort:
            annotations.append("configured")
        if override is not None and override.effort == effort:
            annotations.append("override")
            annotations.append("current")
        elif override is None and configured == effort:
            annotations.append("current")
        return annotations

    def action_choose(self, key: str) -> None:
        if key == "0":
            if self._mode == "edit":
                self.dismiss(DefaultEffortLevelChoice(None))
            return
        try:
            effort = EFFORT_LEVELS_ORDERED[int(key) - 1]
        except (IndexError, ValueError):
            return
        self.dismiss(DefaultEffortLevelChoice(effort))

    def action_cancel(self) -> None:
        self.dismiss(None)


def _append_effort(text: Text, effort: str | None) -> None:
    if effort is None:
        text.append("provider default", style="dim")
    else:
        text.append("@ ", style="dim")
        text.append(effort, style="bold #AF87FF")


__all__ = [
    "DefaultEffortAction",
    "DefaultEffortActionModal",
    "DefaultEffortLevelChoice",
    "DefaultEffortLevelModal",
    "DefaultEffortPickerMode",
]
