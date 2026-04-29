"""Temporary default LLM provider/model override modal.

A leader-mode (``,P`` by default) action that lets the user pick a
provider/model and an expiry duration to temporarily override SASE's
default for new agent launches.  Doesn't edit ``~/.config/sase/sase.yml``;
state lives in ``~/.sase/llm_override.json`` (see
:mod:`sase.llm_provider.temporary_override`).

Flow
----
1. The top-level modal shows the current state:

   - **No override active:** ``Default: <provider>(<model>)`` plus a
     ``[s] Set override`` action.
   - **Override active:** ``Active: <provider>(<model>) expires in 47m``
     plus ``[c] Change`` and ``[x] Clear`` actions.

2. ``Set`` / ``Change`` push :class:`ModelPickerModal` (with the
   "Same as planner" entry hidden — only concrete picks make sense
   here).  Selecting ``Custom...`` then pushes
   :class:`CustomModelInputModal` for a freeform ``provider/model``.

3. After a model is chosen, push the duration picker (presets
   ``15m``/``30m``/``1h``/``2h``/``4h``/``Until cleared`` plus a
   freeform input that uses
   :func:`parse_override_duration`).

The composite modal dismisses with a :class:`TemporaryOverrideResult`
(``"set"`` / ``"cleared"`` / ``"cancelled"``) so the caller can decide
what to notify.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Static

from sase.llm_provider import (
    TemporaryLLMOverride,
    clear_temporary_override,
    get_active_temporary_override,
    parse_override_duration,
    resolve_effective_default_provider_model,
    set_temporary_override,
)
from sase.llm_provider.registry import format_provider_model_label

from .custom_model_input_modal import CustomModelInputModal
from .model_picker_modal import CUSTOM_SENTINEL, ModelPickerModal


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

ResultAction = Literal["set", "cleared", "cancelled"]


@dataclass(frozen=True)
class TemporaryOverrideResult:
    """Outcome of the override modal flow.

    ``action`` indicates which terminal branch ran:

    - ``"set"``: a new override was written; ``override`` is the active
      :class:`TemporaryLLMOverride`.
    - ``"cleared"``: an existing override was removed; ``override`` is
      ``None``.
    - ``"cancelled"``: user backed out at any step; ``override`` is
      ``None``.
    """

    action: ResultAction
    override: TemporaryLLMOverride | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_remaining(seconds: float) -> str:
    """Format an integer-second remaining duration as ``"1h30m"`` etc."""
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs and not hours and not minutes:
        parts.append(f"{secs}s")
    return "".join(parts) or "0s"


def _format_duration_chosen(seconds: float | None) -> str:
    """Render the chosen duration for the success notification."""
    if seconds is None:
        return "until cleared"
    return _format_remaining(seconds)


# ---------------------------------------------------------------------------
# Duration picker modal
# ---------------------------------------------------------------------------


_DURATION_PRESETS: list[tuple[str, str, float | None]] = [
    ("1", "15m", 15 * 60.0),
    ("2", "30m", 30 * 60.0),
    ("3", "1h", 60 * 60.0),
    ("4", "2h", 2 * 60 * 60.0),
    ("5", "4h", 4 * 60 * 60.0),
    ("6", "Until cleared", None),
]


class _DurationPickerModal(ModalScreen["float | None | str"]):
    """Pick how long the override should last.

    Dismisses with one of:

    - ``float`` (seconds) — a finite duration was chosen.
    - ``None`` — "Until cleared" (no expiry).
    - ``"__cancel__"`` — user cancelled.
    """

    BINDINGS = [
        ("1", "preset_1", "15m"),
        ("2", "preset_2", "30m"),
        ("3", "preset_3", "1h"),
        ("4", "preset_4", "2h"),
        ("5", "preset_5", "4h"),
        ("6", "preset_6", "Until cleared"),
        ("c", "open_custom", "Custom"),
        ("escape", "cancel_or_back", "Cancel"),
        ("q", "cancel_or_back", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="override-duration-container"):
            with Vertical(id="override-duration-body"):
                yield Label(
                    "[bold cyan]Override Duration[/bold cyan]",
                    id="override-duration-title",
                )
                for key, label, _ in _DURATION_PRESETS:
                    yield Static(
                        f"  {key}   {label}",
                        classes="override-duration-row",
                    )
                yield Static("", classes="override-duration-spacer")
                yield Static("  c   Custom…", classes="override-duration-row")
                yield Static("", classes="override-duration-spacer")
                yield Static("  esc  cancel", classes="override-duration-row")
                yield Input(
                    placeholder="e.g., 30m, 2h, 1h30m, until cleared",
                    id="override-duration-custom-input",
                    classes="hidden",
                    disabled=True,
                )
                yield Label(
                    "",
                    id="override-duration-custom-error",
                    classes="hidden",
                )

    def _dismiss_preset(self, idx: int) -> None:
        seconds = _DURATION_PRESETS[idx][2]
        # ModalScreen dismiss accepts ``None``; we wrap as a tuple-free
        # union by passing seconds (may be None for "Until cleared").
        self.dismiss(seconds)

    def action_preset_1(self) -> None:
        self._dismiss_preset(0)

    def action_preset_2(self) -> None:
        self._dismiss_preset(1)

    def action_preset_3(self) -> None:
        self._dismiss_preset(2)

    def action_preset_4(self) -> None:
        self._dismiss_preset(3)

    def action_preset_5(self) -> None:
        self._dismiss_preset(4)

    def action_preset_6(self) -> None:
        self._dismiss_preset(5)

    def action_open_custom(self) -> None:
        custom_input = self.query_one("#override-duration-custom-input", Input)
        custom_input.disabled = False
        custom_input.remove_class("hidden")
        custom_input.value = ""
        custom_input.focus()

    def action_cancel_or_back(self) -> None:
        custom_input = self.query_one("#override-duration-custom-input", Input)
        if not custom_input.has_class("hidden") and custom_input.has_focus:
            custom_input.add_class("hidden")
            custom_input.disabled = True
            custom_input.value = ""
            error = self.query_one("#override-duration-custom-error", Label)
            error.update("")
            error.add_class("hidden")
            return
        self.dismiss("__cancel__")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "override-duration-custom-input":
            return
        raw = event.input.value.strip()
        error = self.query_one("#override-duration-custom-error", Label)
        try:
            seconds = parse_override_duration(raw)
        except ValueError as exc:
            error.update(f"Invalid duration: {exc}")
            error.remove_class("hidden")
            event.input.focus()
            return
        self.dismiss(seconds)


# ---------------------------------------------------------------------------
# Top-level override modal
# ---------------------------------------------------------------------------


class TemporaryLLMOverrideModal(ModalScreen[TemporaryOverrideResult]):
    """Set, change, or clear the temporary default LLM override.

    Always dismisses with a :class:`TemporaryOverrideResult` describing
    which terminal branch ran (``set`` / ``cleared`` / ``cancelled``).
    """

    BINDINGS = [
        ("s", "set_or_change", "Set / Change"),
        ("c", "set_or_change", "Set / Change"),
        ("x", "clear", "Clear"),
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._active: TemporaryLLMOverride | None = get_active_temporary_override()

    # -- compose --------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Container(id="override-container"):
            with Vertical(id="override-body"):
                yield Label(
                    "[bold cyan]Temporary Model Override[/bold cyan]",
                    id="override-title",
                )
                yield Static(self._render_state_line(), id="override-state-line")
                yield Static("", classes="override-spacer")
                for line in self._render_action_lines():
                    yield Static(line, classes="override-action-row")
                yield Static("", classes="override-spacer")
                yield Static(
                    "  esc  cancel",
                    classes="override-action-row",
                )

    # -- presentation helpers ------------------------------------------

    def _render_state_line(self) -> str:
        if self._active is not None:
            label = format_provider_model_label(
                self._active.provider, self._active.model
            )
            if self._active.expires_at is None:
                tail = "no expiry"
            else:
                import time

                remaining = self._active.expires_at - time.time()
                tail = f"expires in {_format_remaining(remaining)}"
            return f"[bold yellow]Active:[/bold yellow] {label} ({tail})"

        provider_name, model_name = resolve_effective_default_provider_model()
        label = format_provider_model_label(provider_name, model_name)
        return f"[dim]Default:[/dim] {label}"

    def _render_action_lines(self) -> list[str]:
        if self._active is not None:
            return [
                "  c   Change override",
                "  x   Clear override",
            ]
        return [
            "  s   Set override",
        ]

    # -- actions --------------------------------------------------------

    def action_cancel(self) -> None:
        self.dismiss(TemporaryOverrideResult(action="cancelled"))

    def action_set_or_change(self) -> None:
        """Push the model picker; threads through duration picker on success."""
        self.app.push_screen(
            ModelPickerModal(
                title="Pick Override Model",
                include_default_option=False,
            ),
            callback=self._on_model_picked,
        )

    def action_clear(self) -> None:
        if self._active is None:
            # Nothing to clear; treat as cancel rather than a noisy error.
            self.dismiss(TemporaryOverrideResult(action="cancelled"))
            return
        clear_temporary_override()
        self.dismiss(TemporaryOverrideResult(action="cleared"))

    # -- callbacks ------------------------------------------------------

    def _on_model_picked(self, result: str | None) -> None:
        if result is None:
            # User cancelled the picker — back out, leaving any existing
            # override untouched.  Stay open so they can choose again.
            return
        if result == CUSTOM_SENTINEL:
            self.app.push_screen(
                CustomModelInputModal(
                    title="Custom Override Model",
                    hint="Format: provider/model  or  model",
                    placeholder="e.g. codex/o3",
                ),
                callback=self._on_custom_picked,
            )
            return
        self._raw_model = result
        self._open_duration_picker()

    def _on_custom_picked(self, result: str | None) -> None:
        if result is None:
            return
        self._raw_model = result
        self._open_duration_picker()

    def _open_duration_picker(self) -> None:
        self.app.push_screen(
            _DurationPickerModal(),
            callback=self._on_duration_picked,
        )

    def _on_duration_picked(self, result: float | None | str) -> None:
        # ``"__cancel__"`` is the duration modal's cancel sentinel —
        # ``None`` from that modal is a real value ("until cleared").
        if isinstance(result, str) and result == "__cancel__":
            return
        seconds: float | None
        if isinstance(result, str):
            # Defensive: any other string is unexpected — treat as cancel.
            return
        seconds = result
        try:
            override = set_temporary_override(
                self._raw_model,
                seconds,
                source="ace",
            )
        except ValueError as exc:
            self.notify(f"Invalid override: {exc}", severity="error")
            return
        label = format_provider_model_label(override.provider, override.model)
        self.notify(
            f"Temporary LLM override: {label} for {_format_duration_chosen(seconds)}"
        )
        self.dismiss(TemporaryOverrideResult(action="set", override=override))
