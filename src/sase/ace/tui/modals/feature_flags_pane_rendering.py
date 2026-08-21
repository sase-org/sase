"""Pure render helpers for the Config Flags pane.

Row, card, footer, empty-state, and confirmation copy live here so colors
and text can be unit-tested without mounting Textual widgets.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from sase.bead.flag_due import FlagRemovalState
from sase.bead_flag_presentation import FLAG_DUE_STYLES, flag_due_presentation
from sase.feature_flags.cli_render import on_off, source_text
from sase.feature_flags.cli_summary import summarize_flag_views
from sase.feature_flags.cli_views import FlagView
from sase.feature_flags.env import SASE_FEATURE_FLAGS_ENV
from sase.feature_flags.models import (
    FeatureFlagDecision,
    FeatureFlagDiagnostic,
    FlagSource,
)

FLAGS_PANE_ACCENT = "#00D7AF"
_COLOR_LABEL = "dim"
_ON_STYLE = "bold green"
_OFF_STYLE = "dim"
_BETA_STYLE = "italic cyan"
_SUNSET_STYLE = "italic magenta"
_SHADOW_STYLE = "bold yellow"
_ERROR_STYLE = "bold red"
_WARNING_STYLE = "bold yellow"

_ON_GLYPH = "●"
_OFF_GLYPH = "○"
_BETA_CHIP = "β"
_SUNSET_CHIP = "↗"

ROLLOUT_FLAG_KEY = "admin_center_flags"
ROLLOUT_RECOVERY_COMMAND = "sase flag enable admin_center_flags"

_PROCESS_PIN_SOURCES: frozenset[FlagSource] = frozenset({"override", "cli"})

_LIST_RAIL_CHROME = 6
_LIST_RAIL_MIN_WIDTH = 32
_LIST_RAIL_MAX_WIDTH = 52
_LIST_RAIL_DETAIL_RESERVED = 56

_SOURCE_FILTER_LABELS: dict[FlagSource, tuple[str, ...]] = {
    "default": ("default", "registry"),
    "user": ("user", "config"),
    "overlay": ("overlay", "config"),
    "local": ("local", "config"),
    "state": ("state", "saved"),
    "override": ("override", "test"),
    "env": ("env", "environment", SASE_FEATURE_FLAGS_ENV.casefold()),
    "cli": ("cli", "--enable-feature", "--disable-feature"),
}


@dataclass(frozen=True)
class FlagToggleConfirmation:
    """Cancel-first confirmation copy for one Flags-pane toggle."""

    title: str
    message: str
    subject: str


def is_shadowed_decision(decision: FeatureFlagDecision, saved: bool | None) -> bool:
    """Return whether a higher-precedence source currently wins over *saved*."""
    if decision.source in _PROCESS_PIN_SOURCES:
        return True
    if decision.source == "env" and saved is not None and decision.enabled != saved:
        return True
    return False


def flag_matches_filter(view: FlagView, pattern: str) -> bool:
    """Return whether *view* matches the Flags-pane filter pattern."""
    needle = pattern.casefold().strip()
    if not needle:
        return True
    haystacks = [
        str(view.definition.key),
        view.definition.description,
        view.definition.kind,
        "on" if view.decision.enabled else "off",
        "enabled" if view.decision.enabled else "disabled",
        view.decision.source,
        view.decision.source_detail,
        "saved" if view.saved is not None else "unset",
        on_off(view.saved) if view.saved is not None else "",
        _BETA_CHIP if view.definition.kind == "beta" else _SUNSET_CHIP,
        *(_SOURCE_FILTER_LABELS.get(view.decision.source, ())),
    ]
    if view.bead is not None:
        haystacks.extend((view.bead.id, view.bead.status))
    if view.due_state is not None:
        haystacks.append(view.due_state)
    return any(needle in item.casefold() for item in haystacks if item)


def filter_flag_views(
    views: tuple[FlagView, ...], pattern: str
) -> tuple[FlagView, ...]:
    """Return views whose key/description/kind/state/provenance match *pattern*."""
    return tuple(view for view in views if flag_matches_filter(view, pattern))


def build_panel_header(
    views: tuple[FlagView, ...],
    *,
    loading: bool = False,
    error: str | None = None,
    accent: str = FLAGS_PANE_ACCENT,
) -> Text:
    """Build the ``FLAGS  ·  N registered  ·  N on  ·  N saved`` header."""
    text = Text()
    text.append("FLAGS", style=f"bold {accent}")
    if loading:
        text.append("  ·  loading…", style="dim")
        return text
    if error:
        text.append("  ·  ", style="dim")
        text.append("error", style=_ERROR_STYLE)
        return text
    summary = summarize_flag_views(views)
    saved = sum(1 for view in views if view.saved is not None)
    text.append(f"  ·  {summary.total} registered", style="dim")
    on_word = "on"
    text.append("  ·  ", style="dim")
    text.append(f"{summary.enabled} {on_word}", style=_ON_STYLE)
    text.append("  ·  ", style="dim")
    text.append(f"{saved} saved", style="dim")
    return text


def build_flag_row_text(view: FlagView) -> Text:
    """Build one list row: on/off glyph, kind chip, and flag key."""
    enabled = view.decision.enabled
    text = Text()
    text.append(
        f"{_ON_GLYPH if enabled else _OFF_GLYPH} ",
        style=_ON_STYLE if enabled else _OFF_STYLE,
    )
    text.append(
        "ON   " if enabled else "OFF  ",
        style=_ON_STYLE if enabled else _OFF_STYLE,
    )
    if view.definition.kind == "sunset":
        text.append(f"{_SUNSET_CHIP} ", style=_SUNSET_STYLE)
    else:
        text.append(f"{_BETA_CHIP} ", style=_BETA_STYLE)
    text.append(str(view.definition.key))
    if is_shadowed_decision(view.decision, view.saved):
        text.append("  !", style=_SHADOW_STYLE)
    if view.due_state == "due":
        text.append("  due", style=_ERROR_STYLE)
    elif view.due_state == "soon":
        text.append("  soon", style=_WARNING_STYLE)
    return text


def flag_rail_width(views: tuple[FlagView, ...], *, available_width: int) -> int:
    """Return the width ``#feature-flags-pane-list`` should take."""
    if not views:
        return _LIST_RAIL_MIN_WIDTH
    widest = max(build_flag_row_text(view).cell_len for view in views)
    desired = widest + _LIST_RAIL_CHROME
    cap = _LIST_RAIL_MAX_WIDTH
    if available_width > 0:
        room = available_width - _LIST_RAIL_DETAIL_RESERVED - 1
        cap = min(cap, max(_LIST_RAIL_MIN_WIDTH, room))
    return max(_LIST_RAIL_MIN_WIDTH, min(cap, desired))


def build_detail_title(view: FlagView) -> Text:
    """Build the detail card title: key plus effective on/off and kind."""
    enabled = view.decision.enabled
    text = Text()
    text.append(str(view.definition.key), style="bold")
    text.append("  ")
    text.append(
        "ON" if enabled else "OFF",
        style=_ON_STYLE if enabled else _OFF_STYLE,
    )
    text.append("  ·  ", style="dim")
    kind = view.definition.kind.upper()
    kind_style = _SUNSET_STYLE if view.definition.kind == "sunset" else _BETA_STYLE
    text.append(kind, style=kind_style)
    return text


def build_detail_description(view: FlagView) -> Text:
    """Build the full registry description for the detail card."""
    return Text(view.definition.description)


def build_detail_meta(
    view: FlagView,
    *,
    state_path: str,
    diagnostics: tuple[FeatureFlagDiagnostic, ...] = (),
    today: date | None = None,
    release: str | None = None,
) -> RenderableType:
    """Build the provenance, bead, and diagnostic block for one flag."""
    sections: list[RenderableType] = []
    if is_shadowed_decision(view.decision, view.saved):
        sections.append(_shadow_warning(view.decision))
    sections.append(
        _property_grid(view, state_path=state_path, today=today, release=release)
    )
    if diagnostics:
        sections.append(_diagnostics_block(diagnostics))
    return Group(*sections)


def build_loading_card() -> tuple[Text, Text, Text]:
    """Return title/description/meta for the lightweight loading shell."""
    return Text(""), Text("Loading…", style="dim"), Text("")


def build_empty_catalog_message() -> Text:
    """Build the card shown when no feature flags are registered."""
    text = Text(justify="left")
    text.append("No feature flags are registered.", style="dim")
    return text


def build_no_match_message(pattern: str) -> Text:
    """Build the card shown when a filter matches no flags."""
    text = Text(justify="left")
    text.append("No flags match ", style="dim")
    text.append(pattern, style="bold")
    text.append(".", style="dim")
    return text


def build_error_message(error: str) -> Text:
    """Build the card shown when the Flags pane failed to load."""
    text = Text()
    text.append("Could not load feature flags.\n\n", style=_ERROR_STYLE)
    text.append(error, style="dim")
    return text


def build_corrupt_state_message(
    diagnostics: tuple[FeatureFlagDiagnostic, ...],
) -> Text:
    """Build the card shown when saved state is unreadable."""
    text = Text()
    text.append("Saved feature-flag state is unreadable.\n\n", style=_ERROR_STYLE)
    text.append(
        "Registered flags still appear using registry defaults. "
        "Repair or remove the machine-state file, then retry.\n\n",
        style="dim",
    )
    for diagnostic in diagnostics:
        text.append(
            f"{diagnostic.severity}: {diagnostic.message}\n", style=_ERROR_STYLE
        )
    return text


def build_panel_footer(
    *,
    filter_open: bool,
    has_selection: bool,
    mutating: bool,
) -> Text:
    """Build the one-line contextual footer."""
    text = Text()
    if mutating:
        text.append("saving…  ·  ACE and AXE will restart", style="dim")
        return text
    if filter_open:
        text.append("esc", style="bold")
        text.append(" close filter  ·  ", style="dim")
        text.append("enter", style="bold")
        text.append(" apply", style="dim")
        return text
    text.append("/", style="bold")
    text.append(" filter  ·  ", style="dim")
    if has_selection:
        text.append("enter", style="bold")
        text.append(" toggle  ·  ", style="dim")
    text.append("r", style="bold")
    text.append(" refresh  ·  ", style="dim")
    text.append("changes restart ACE + AXE", style="dim")
    return text


def build_toggle_confirmation(
    view: FlagView,
    *,
    state_path: str,
) -> FlagToggleConfirmation:
    """Build cancel-first confirmation copy for toggling *view*."""
    target_enabled = not view.decision.enabled
    current = on_off(view.decision.enabled).upper()
    target = on_off(target_enabled).upper()
    lines = [
        f"Flag: {view.definition.key}",
        f"Change: {current} -> {target}",
        f"Saved path: {state_path or '(machine state under SASE_HOME)'}",
        f"Description: {view.definition.description}",
    ]
    if is_shadowed_decision(view.decision, view.saved):
        lines.append("")
        lines.append(_shadow_plain(view.decision))
    if str(view.definition.key) == ROLLOUT_FLAG_KEY and not target_enabled:
        lines.append("")
        lines.append(
            "The Flags pane will disappear after restart. "
            f"Recover with: {ROLLOUT_RECOVERY_COMMAND}"
        )
    return FlagToggleConfirmation(
        title="Toggle feature flag",
        message="ACE and AXE restart after active procs finish.",
        subject="\n".join(lines),
    )


def _property_grid(
    view: FlagView,
    *,
    state_path: str,
    today: date | None,
    release: str | None,
) -> Table:
    grid = Table.grid(expand=True, padding=(0, 2, 0, 0))
    grid.add_column(no_wrap=True)
    grid.add_column(ratio=1, overflow="fold")
    grid.add_column(no_wrap=True)
    grid.add_column(ratio=1, overflow="fold")
    grid.add_row(
        Text("EFFECTIVE", style=_COLOR_LABEL),
        _on_off_text(view.decision.enabled),
        Text("SOURCE", style=_COLOR_LABEL),
        source_text(view.decision),
    )
    saved = (
        _on_off_text(view.saved) if view.saved is not None else Text("—", style="dim")
    )
    grid.add_row(
        Text("DEFAULT", style=_COLOR_LABEL),
        _on_off_text(view.definition.default),
        Text("SAVED", style=_COLOR_LABEL),
        saved,
    )
    bead_id = view.bead.id if view.bead is not None else "—"
    bead_status = view.bead.status if view.bead is not None else "—"
    grid.add_row(
        Text("BEAD", style=_COLOR_LABEL),
        Text(bead_id, style="dim" if view.bead is None else ""),
        Text("STATUS", style=_COLOR_LABEL),
        Text(bead_status, style="dim" if view.bead is None else ""),
    )
    remove_by = "—"
    bead = view.bead
    if bead is not None and bead.remove_by_date and bead.remove_by_release:
        remove_by = f"{bead.remove_by_date} / {bead.remove_by_release}"
    due_cell: RenderableType = Text("—", style="dim")
    if (
        bead is not None
        and bead.remove_by_date
        and bead.remove_by_release
        and today is not None
        and release is not None
    ):
        presentation = flag_due_presentation(
            bead.remove_by_date,
            bead.remove_by_release,
            today=today,
            release=release,
        )
        due_cell = Text(presentation.label, style=presentation.style.rich)
    elif view.due_state is not None:
        due_cell = _due_state_text(view.due_state)
    grid.add_row(
        Text("REMOVE BY", style=_COLOR_LABEL),
        Text(remove_by, style="dim" if remove_by == "—" else ""),
        Text("DUE", style=_COLOR_LABEL),
        due_cell,
    )
    grid.add_row(
        Text("STATE", style=_COLOR_LABEL),
        Text(state_path or "—", style="dim" if not state_path else ""),
        Text(""),
        Text(""),
    )
    return grid


def _on_off_text(value: bool) -> Text:
    return Text(
        on_off(value),
        style=_ON_STYLE if value else _OFF_STYLE,
    )


def _due_state_text(state: FlagRemovalState) -> Text:
    style = FLAG_DUE_STYLES[state].rich
    if state == "due":
        style = _ERROR_STYLE
    elif state == "soon":
        style = _WARNING_STYLE
    return Text(state, style=style)


def _shadow_warning(decision: FeatureFlagDecision) -> Text:
    text = Text()
    text.append("Forced for this process by ", style=_SHADOW_STYLE)
    text.append(_shadow_source_label(decision), style=_SHADOW_STYLE)
    text.append(
        ". Saving still restarts ACE and AXE, but the saved value will not "
        "win until that override is removed.",
        style=_SHADOW_STYLE,
    )
    return text


def _shadow_plain(decision: FeatureFlagDecision) -> str:
    return (
        f"Forced for this process by {_shadow_source_label(decision)}. "
        "Saving still restarts ACE and AXE, but the saved value will not "
        "win until that override is removed."
    )


def _shadow_source_label(decision: FeatureFlagDecision) -> str:
    if decision.source == "cli":
        return decision.source_detail or (
            "--enable-feature" if decision.enabled else "--disable-feature"
        )
    if decision.source == "env":
        return decision.source_detail or SASE_FEATURE_FLAGS_ENV
    if decision.source_detail:
        return f"{decision.source}:{decision.source_detail}"
    return decision.source


def _diagnostics_block(diagnostics: tuple[FeatureFlagDiagnostic, ...]) -> Text:
    text = Text()
    text.append("\n")
    for diagnostic in diagnostics:
        style = _ERROR_STYLE if diagnostic.severity == "error" else _WARNING_STYLE
        text.append(f"{diagnostic.severity}: {diagnostic.message}\n", style=style)
    return text


__all__ = [
    "FlagToggleConfirmation",
    "FLAGS_PANE_ACCENT",
    "ROLLOUT_FLAG_KEY",
    "ROLLOUT_RECOVERY_COMMAND",
    "build_corrupt_state_message",
    "build_detail_description",
    "build_detail_meta",
    "build_detail_title",
    "build_empty_catalog_message",
    "build_error_message",
    "build_flag_row_text",
    "build_loading_card",
    "build_no_match_message",
    "build_panel_footer",
    "build_panel_header",
    "build_toggle_confirmation",
    "filter_flag_views",
    "flag_matches_filter",
    "flag_rail_width",
    "is_shadowed_decision",
]
