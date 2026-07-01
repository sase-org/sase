"""The Models panel — view every model alias and manage temporary overrides.

A leader-mode (``,m`` by default) surface that lists every configured and
implicit model alias (``default`` / ``coder`` / ``<provider>_coder`` /
``epic_creator`` / ``epic_lander`` / ``phase_worker`` plus any user-defined
``llm_provider.model_aliases`` entry) with its effective provider/model, its
provenance, and any active temporary override.

From the selected row the user can set/change a time-bound temporary override
(**o**) or clear one (**x**) for *that alias* — reusing the shared model picker,
custom-model input, and duration picker. The ``default`` alias keeps its existing
behavior: an override on it drives the no-``%model`` launch default and the gold
top-bar pill (see :class:`sase.ace.tui.widgets.LLMOverrideIndicator`).

The user can also change an alias's *persistent* configured value with **e**
(Edit) or unset it back to the implicit fallback with **r** (Reset). Both go
through the Rust-backed, source-preserving config-edit path
(:mod:`sase.config.edit`), preview the diff before writing
(:class:`sase.ace.tui.modals.models_panel_edit.AliasEditPreviewModal`), and then
offer a ``use_chezmoi``-aware commit+push. Temporary-override state lives in
``~/.sase/llm_override.json`` (see :mod:`sase.llm_provider.temporary_override`).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets._option_list import Option

from sase.ace.tui.provider_styles import provider_model_badge_markup
from sase.config import ConfigEditOp
from sase.llm_provider import (
    AliasView,
    build_alias_views,
    clear_alias_override,
    parse_override_duration,
    set_alias_override,
)
from sase.llm_provider.config import (
    DEFAULT_MODEL_ALIAS_NAME,
)
from sase.llm_provider.registry import format_provider_model_label
from sase.llm_provider.temporary_override import TemporaryLLMOverride

from .base import OptionListNavigationMixin
from .custom_model_input_modal import CustomModelInputModal
from .duration_choice_modal import (
    DURATION_CHOICE_CANCELLED,
    DurationChoice,
    DurationChoiceCancelled,
    DurationChoiceModal,
)
from .model_picker_modal import CUSTOM_SENTINEL, ModelPickerModal
from .models_panel_edit import AliasEditPreviewModal
from .models_panel_edit_helpers import (
    AliasCommitOffer,
    AliasEditOutcome,
    build_alias_commit_offer,
)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelsPanelResult:
    """Outcome of a Models panel session.

    ``changed`` is ``True`` when at least one temporary override was set or
    cleared while the panel was open, so the caller knows to refresh top-bar
    override indicators.
    """

    changed: bool = False


# ---------------------------------------------------------------------------
# Duration / time formatting helpers
# ---------------------------------------------------------------------------


def _now() -> float:
    """Return the current wall-clock time (indirection lets tests pin it)."""
    return time.time()


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


def _parse_override_custom(raw: str) -> float | None:
    try:
        return parse_override_duration(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid duration: {exc}") from exc


# ---------------------------------------------------------------------------
# Duration picker modal (shared with the old default-override flow)
# ---------------------------------------------------------------------------


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
# Row rendering
# ---------------------------------------------------------------------------

_KIND_CELL = 13
_NAME_CELL = 16

_KIND_LABELS: dict[str, str] = {
    "default": "default",
    "role": "role",
    "provider_coder": "coder",
    "user": "user",
}

_KIND_STYLES: dict[str, str] = {
    "default": "bold #87D7FF",
    "role": "bold #87D7AF",
    "provider_coder": "bold #AFAFFF",
    "user": "bold #D7AF87",
}

_OVERRIDE_TAG_STYLE = "bold #AF87FF"
_CONFIGURED_TAG_STYLE = "#87D787"
_IMPLICIT_TAG_STYLE = "dim #9E9E9E"


def _pad(value: str, width: int) -> str:
    """Truncate-or-pad *value* to exactly *width* columns."""
    if len(value) > width:
        return value[: max(0, width - 1)] + "…"
    return value.ljust(width)


def _kind_label(view: AliasView) -> str:
    """Return the small kind badge text for *view*."""
    return _KIND_LABELS.get(view.kind, view.kind)


def _override_chip(override: TemporaryLLMOverride, now: float) -> str:
    """Render the active-override state chip (``override · 15m left``)."""
    if override.expires_at is None:
        return "override · until cleared"
    return f"override · {_format_remaining(override.expires_at - now)} left"


def _state_tag(view: AliasView, now: float) -> tuple[str, str]:
    """Return ``(text, style)`` for the provenance / override state column."""
    if view.override is not None:
        return _override_chip(view.override, now), _OVERRIDE_TAG_STYLE
    if view.configured:
        return "configured", _CONFIGURED_TAG_STYLE
    if view.name == DEFAULT_MODEL_ALIAS_NAME:
        return "implicit", _IMPLICIT_TAG_STYLE
    return "implicit → @default", _IMPLICIT_TAG_STYLE


def _render_alias_row(view: AliasView, *, now: float) -> Text:
    """Render one alias row as a single-line Rich ``Text``.

    Layout: ``<kind badge> <alias name> <PROVIDER(model) badge> <state tag>``.
    Building a ``Text`` (rather than a markup string) keeps alias/model values
    literal so a stray bracket in a config value can never break rendering.
    """
    text = Text(no_wrap=True, overflow="ellipsis")
    text.append(_pad(_kind_label(view), _KIND_CELL), style=_KIND_STYLES.get(view.kind))
    text.append(" ")
    text.append(_pad(view.name, _NAME_CELL), style="bold")
    text.append(" ")
    text.append_text(
        Text.from_markup(provider_model_badge_markup(view.provider, view.model))
    )
    text.append("   ")
    tag_text, tag_style = _state_tag(view, now)
    text.append(tag_text, style=tag_style)
    return text


# ---------------------------------------------------------------------------
# Models panel
# ---------------------------------------------------------------------------


class ModelsPanel(OptionListNavigationMixin, ModalScreen[ModelsPanelResult]):
    """View every model alias and set/clear per-alias temporary overrides.

    Dismisses with a :class:`ModelsPanelResult` whose ``changed`` flag reports
    whether any override was written while the panel was open.
    """

    _option_list_id = "models-panel-list"

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("j", "next_option", "Next"),
        ("k", "prev_option", "Previous"),
        ("down", "next_option", "Next"),
        ("up", "prev_option", "Previous"),
        ("ctrl+n", "next_option", "Next"),
        ("ctrl+p", "prev_option", "Previous"),
        ("o", "override", "Override"),
        ("x", "clear", "Clear"),
        ("e", "edit", "Edit"),
        ("r", "reset", "Reset"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._changed = False
        self._views: list[AliasView] = []
        self._view_by_name: dict[str, AliasView] = {}
        self._pending_alias = ""
        self._pending_raw_model = ""
        self._pending_edit_alias = ""

    # -- compose --------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Container(id="models-panel-container"):
            yield Static("[bold cyan]Models[/bold cyan]", id="models-panel-title")
            yield OptionList(*self._build_options(), id="models-panel-list")
            yield Static(self._footer_markup(), id="models-panel-footer")

    def on_mount(self) -> None:
        option_list = self.query_one("#models-panel-list", OptionList)
        option_list.focus()
        if option_list.option_count and option_list.highlighted is None:
            option_list.highlighted = 0

    @staticmethod
    def _footer_markup() -> str:
        return (
            "[green]o[/green]=Override  "
            "[green]x[/green]=Clear  "
            "[green]e[/green]=Edit  "
            "[green]r[/green]=Reset  "
            "[dim]j/k[/dim]=Navigate  "
            "[dim]esc[/dim]=Close"
        )

    # -- option building -----------------------------------------------

    def _build_options(self) -> list[Option]:
        now = _now()
        self._views = build_alias_views()
        self._view_by_name = {view.name: view for view in self._views}
        return [
            Option(_render_alias_row(view, now=now), id=view.name)
            for view in self._views
        ]

    def _refresh_rows(self, *, keep: str | None = None) -> None:
        """Rebuild the list in place, preserving the highlighted alias."""
        option_list = self.query_one("#models-panel-list", OptionList)
        preferred = keep or self._highlighted_alias()
        option_list.clear_options()
        option_list.add_options(self._build_options())
        if preferred is not None:
            try:
                option_list.highlighted = option_list.get_option_index(preferred)
                return
            except Exception:
                pass
        if option_list.option_count:
            option_list.highlighted = 0

    def _highlighted_alias(self) -> str | None:
        option_list = self.query_one("#models-panel-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return None
        try:
            option = option_list.get_option_at_index(highlighted)
        except Exception:
            return None
        return str(option.id) if option.id is not None else None

    def _selected_view(self) -> AliasView | None:
        alias = self._highlighted_alias()
        if alias is None:
            return None
        return self._view_by_name.get(alias)

    # -- actions --------------------------------------------------------

    def action_close(self) -> None:
        self.dismiss(ModelsPanelResult(changed=self._changed))

    def action_cancel(self) -> None:
        """Alias for :meth:`action_close` (overrides the navigation mixin)."""
        self.action_close()

    def action_override(self) -> None:
        view = self._selected_view()
        if view is None:
            return
        self._pending_alias = view.name
        self.app.push_screen(
            ModelPickerModal(
                title=f"Override Model — @{view.name}",
                include_default_option=False,
            ),
            callback=self._on_model_picked,
        )

    def action_clear(self) -> None:
        view = self._selected_view()
        if view is None:
            return
        if view.override is None:
            self.notify(f"No active override on @{view.name}", severity="warning")
            return
        clear_alias_override(view.name)
        self.notify(f"Cleared override on @{view.name}")
        self._changed = True
        self._refresh_rows(keep=view.name)

    # -- override flow callbacks ---------------------------------------

    def _on_model_picked(self, result: str | None) -> None:
        if result is None:
            # Picker cancelled — keep the panel open so the user can retry.
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
        self._pending_raw_model = result
        self._open_duration_picker()

    def _on_custom_picked(self, result: str | None) -> None:
        if result is None:
            return
        self._pending_raw_model = result
        self._open_duration_picker()

    def _open_duration_picker(self) -> None:
        self.app.push_screen(_DurationPickerModal(), callback=self._on_duration_picked)

    def _on_duration_picked(
        self, result: float | None | DurationChoiceCancelled
    ) -> None:
        # The duration modal uses a sentinel for cancel so ``None`` stays a real
        # value ("until cleared").
        if isinstance(result, DurationChoiceCancelled):
            return
        seconds: float | None = result
        alias = self._pending_alias
        try:
            override = set_alias_override(
                alias,
                self._pending_raw_model,
                seconds,
                source="ace",
            )
        except ValueError as exc:
            self.notify(f"Invalid override: {exc}", severity="error")
            return
        label = format_provider_model_label(override.provider, override.model)
        self.notify(
            f"@{alias} override: {label} for {_format_duration_chosen(seconds)}"
        )
        self._changed = True
        self._refresh_rows(keep=alias)

    # -- persistent edit / reset ---------------------------------------

    def action_edit(self) -> None:
        view = self._selected_view()
        if view is None:
            return
        self._pending_edit_alias = view.name
        self.app.push_screen(
            ModelPickerModal(
                title=f"Edit Model — @{view.name}",
                include_default_option=False,
            ),
            callback=self._on_edit_model_picked,
        )

    def action_reset(self) -> None:
        view = self._selected_view()
        if view is None:
            return
        if not view.configured:
            self.notify(
                f"@{view.name} has no configured value to reset",
                severity="warning",
            )
            return
        self._open_alias_preview(view.name, ConfigEditOp.unset())

    def _on_edit_model_picked(self, result: str | None) -> None:
        if result is None:
            return
        if result == CUSTOM_SENTINEL:
            self.app.push_screen(
                CustomModelInputModal(
                    title="Custom Alias Value",
                    hint="Format: provider/model, model, or @alias",
                    placeholder="e.g. claude/opus  or  @default",
                ),
                callback=self._on_edit_custom_picked,
            )
            return
        self._open_alias_preview(
            self._pending_edit_alias, ConfigEditOp.set_value(result)
        )

    def _on_edit_custom_picked(self, result: str | None) -> None:
        if result is None:
            return
        self._open_alias_preview(
            self._pending_edit_alias, ConfigEditOp.set_value(result)
        )

    def _open_alias_preview(self, alias: str, op: ConfigEditOp) -> None:
        self.app.push_screen(
            AliasEditPreviewModal(alias, op),
            callback=self._on_alias_edited,
        )

    def _on_alias_edited(self, outcome: AliasEditOutcome | None) -> None:
        if outcome is None:
            return
        verb = "Reset" if outcome.applied.op == "unset" else "Updated"
        self.notify(f"{verb} @{outcome.alias}")
        # A persistent edit does not touch temporary overrides, so ``_changed``
        # (which drives the override indicators) stays as-is; refresh the rows
        # so the configured/effective columns reflect the new value.
        self._refresh_rows(keep=outcome.alias)
        self._offer_commit_push(outcome)

    def _offer_commit_push(self, outcome: AliasEditOutcome) -> None:
        offer = build_alias_commit_offer(
            outcome.applied.path,
            op=outcome.applied.op,
            alias=outcome.alias,
        )
        if offer is None:
            # Not in a git repo (or no pending change) — the file is already
            # written, so just confirm the save without a commit offer.
            return
        from .confirm_action_modal import ConfirmActionModal

        def _on_answer(confirmed: bool | None) -> None:
            if confirmed:
                self._submit_commit_task(offer)

        self.app.push_screen(
            ConfirmActionModal(
                "Commit & Push",
                "Commit and push your model-alias change?",
                subject=offer.rel_path,
                icon="↑",
                confirm_label="Commit & push",
                cancel_label="Skip",
                default="confirm",
            ),
            _on_answer,
        )

    def _submit_commit_task(self, offer: AliasCommitOffer) -> None:
        from sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt_git import (
            run_git_commit_push_sync,
        )
        from sase.ace.tui.actions.task_actions import (
            TrackedTaskCompletion,
            TrackedTaskResult,
        )

        def _task() -> TrackedTaskResult[None]:
            success, message = run_git_commit_push_sync(
                git_root=offer.git_root,
                file_path=offer.file_path,
                commit_message=offer.message,
            )
            return TrackedTaskResult(
                success=success,
                message=message,
                error=None if success else message,
            )

        def _on_complete(completion: TrackedTaskCompletion[None]) -> None:
            self.notify(
                completion.message,
                severity="information" if completion.success else "error",
            )

        submit = getattr(self.app, "_submit_tracked_task", None)
        if submit is None:
            self.notify(
                "Could not commit: background task queue unavailable.",
                severity="error",
            )
            return
        submit(
            "config-commit",
            offer.rel_path,
            offer.git_root,
            _task,
            display_name=f"commit alias {offer.rel_path}",
            dedup_key=f"config-commit:{offer.git_root}:{offer.rel_path}",
            duplicate_message=(
                f"Another config commit is already running for {offer.rel_path}."
            ),
            on_complete=_on_complete,
            reload_on_complete=False,
            notify_on_complete=False,
        )

    # -- enter on the list selects override ----------------------------

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.action_override()
