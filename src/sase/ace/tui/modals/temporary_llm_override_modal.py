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
from textual.widgets import Label, Static

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
from .duration_choice_modal import (
    DURATION_CHOICE_CANCELLED,
    DurationChoice,
    DurationChoiceCancelled,
    DurationChoiceModal,
)
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


def _parse_override_custom(raw: str) -> float | None:
    try:
        return parse_override_duration(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid duration: {exc}") from exc


class _DurationPickerModal(DurationChoiceModal[float | None, DurationChoiceCancelled]):
    """Pick how long the override should last.

    Dismisses with one of:

    - ``float`` (seconds) — a finite duration was chosen.
    - ``None`` — "Until cleared" (no expiry).
    - shared cancel sentinel — user cancelled.
    """

    def __init__(self) -> None:
        super().__init__(
            title="Override Duration",
            choices=[
                DurationChoice(
                    key="1",
                    title="15 minutes",
                    subtitle="Use for quick model checks.",
                    value=15 * 60.0,
                    tone="primary",
                ),
                DurationChoice(
                    key="2",
                    title="30 minutes",
                    subtitle="Keep the override through a short task.",
                    value=30 * 60.0,
                ),
                DurationChoice(
                    key="3",
                    title="1 hour",
                    subtitle="Cover a focused coding session.",
                    value=60 * 60.0,
                ),
                DurationChoice(
                    key="4",
                    title="2 hours",
                    subtitle="Use for a longer implementation block.",
                    value=2 * 60 * 60.0,
                ),
                DurationChoice(
                    key="5",
                    title="4 hours",
                    subtitle="Keep the override for half a day.",
                    value=4 * 60 * 60.0,
                ),
                DurationChoice(
                    key="6",
                    title="Until cleared",
                    subtitle="Persist until you remove it.",
                    value=None,
                    tone="accent",
                ),
            ],
            parse_custom=_parse_override_custom,
            custom_placeholder="e.g., 30m, 2h, 1h30m, until cleared",
            cancel_result=DURATION_CHOICE_CANCELLED,
            id_prefix="override-duration",
        )


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
                    placeholder="e.g. opencode/anthropic/claude-sonnet-4-5",
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

    def _on_duration_picked(
        self, result: float | None | DurationChoiceCancelled
    ) -> None:
        # The duration modal uses a sentinel for cancel so ``None`` stays a real
        # value ("until cleared").
        if isinstance(result, DurationChoiceCancelled):
            return
        seconds: float | None
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
