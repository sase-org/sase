"""Machine-labelled runner-capacity chip for the Agents status row.

Renders ``⌂<machine> cap <load>/<limit>`` at the right of the Agents row,
just before the launch-context cluster. Compact density keeps the ``cap``
label and drops only the machine prefix. The value run shares one color
from the usage-window palette in ``_usage_indicator_palette``, keyed on
free-capacity percent, so a given color means the same amount of headroom
in both places.
"""

from __future__ import annotations

import math
import time
from typing import Any, Literal

from rich.cells import cell_len
from rich.text import Text
from textual import events
from textual.widgets import Static

from ._usage_indicator_palette import (
    usage_percent_color,
    usage_rejected_style,
    usage_zero_value_style,
)

AgentLoadDensity = Literal["full", "compact"]

_CAP_LABEL = "cap "
_TRAILING_SEPARATOR = " · "
_MACHINE_GLYPH = "⌂"
_STALE_GLYPH = "⟳"
_OVER_GLYPH = "▲"
_OVERRIDE_MARK = "*"
_FAULT_MARK = "!"
_HOLDER_TOOLTIP_LIMIT = 12
_INSPECTOR_HINT = ",l opens the capacity inspector"
_REMOTE_NOTE = "This chip is this machine's capacity; remote capacity is not shown."


def _format_load_value(value: object) -> str:
    """Format a runner load/capacity number, preferring integers.

    Non-numeric, ``bool``, or non-finite values render as ``—``. Other
    values round to 2 decimals: whole results render as integers, the rest
    trim trailing zeros. ``-0`` renders as ``0``.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "—"
    number = float(value)
    if not math.isfinite(number):
        return "—"
    rounded = round(number, 2)
    if rounded == 0:
        rounded = 0.0
    if float(rounded).is_integer():
        return str(int(rounded))
    return f"{rounded:.2f}".rstrip("0").rstrip(".")


def _free_capacity_percent(limit: float, occupied: float) -> float:
    """Return free capacity percent for *limit*/*occupied*, de-noised."""
    free = max(0.0, limit - max(0.0, occupied))
    return round(free / limit * 100.0, 6)


def _resolve_machine_label() -> str:
    """Return this host's machine label without importing config at module load."""
    try:
        from sase.core.local_machine import local_machine_label

        label = local_machine_label()
    except Exception:
        return "local"
    if isinstance(label, str) and label.strip():
        return label.strip()
    return "local"


def _override_marks(provenance: Any, *, now: float) -> tuple[bool, bool]:
    """Return ``(active, warning)`` for the chip's override ``*`` marker."""
    if provenance is None:
        return False, False
    active = None
    lookup = getattr(provenance, "active_override", None)
    if callable(lookup):
        try:
            active = lookup(now)
        except Exception:
            active = None
    if active is None:
        return False, False
    expires_at = getattr(active, "expires_at", None)
    created_at = getattr(active, "created_at", None)
    warning = False
    if expires_at is None and isinstance(created_at, (int, float)):
        from sase.core.runner_slots import CAPACITY_OVERRIDE_WARNING_AFTER_SECONDS

        warning = (now - float(created_at)) >= CAPACITY_OVERRIDE_WARNING_AFTER_SECONDS
    return True, warning


def _is_stale(report_age_seconds: float | None) -> bool:
    """Return whether the report is older than ~2.5 poll cycles."""
    if report_age_seconds is None:
        return False
    from sase.core.runner_slots import CAPACITY_REPORT_STALE_AFTER_SECONDS

    return report_age_seconds >= CAPACITY_REPORT_STALE_AFTER_SECONDS


def _agent_load_value_style(
    limit: float,
    occupied: float | None,
    *,
    dark: bool,
    fault: bool,
    over_limit: bool,
) -> str:
    """Return the value-run style for a known load/limit pair."""
    if fault:
        return usage_zero_value_style(dark=dark)
    if occupied is None or limit <= 0:
        return "dim"
    if over_limit or round(occupied, 2) >= round(limit, 2):
        return usage_zero_value_style(dark=dark)
    return f"bold {usage_percent_color(_free_capacity_percent(limit, occupied), dark=dark)}"


def _cap_chrome(density: AgentLoadDensity, machine_label: str) -> str:
    """Return the dim prefix: machine + ``cap`` in full, ``cap`` in compact."""
    if density == "full":
        return f"{_MACHINE_GLYPH}{machine_label} {_CAP_LABEL}"
    return _CAP_LABEL


def _value_text(
    limit: float,
    occupied: float | None,
    *,
    fault: bool,
    estimate: bool,
) -> str:
    """Return the ``load/limit`` run, with ``?`` / ``~`` / ``—`` as needed."""
    limit_text = _format_load_value(limit) if limit > 0 else "—"
    if limit <= 0:
        return "—/—"
    if fault:
        return f"?/{limit_text}"
    if occupied is None:
        return f"—/{limit_text}"
    occupied_text = _format_load_value(occupied)
    if estimate:
        return f"~{occupied_text}/{limit_text}"
    return f"{occupied_text}/{limit_text}"


def _override_mark_style(*, dark: bool, warning: bool) -> str:
    """Return dim chrome for a fresh override, warning color for a stale one."""
    if warning:
        return f"bold {'#EBC04F' if dark else '#775800'}"
    return "dim"


def _build_agent_load_text(
    limit: float,
    occupied: float | None,
    *,
    dark: bool,
    density: AgentLoadDensity,
    machine_label: str = "local",
    source: str = "estimate",
    report_age_seconds: float | None = None,
    accounting_valid: bool | None = None,
    over_limit: bool | None = None,
    override_active: bool = False,
    override_warning: bool = False,
) -> Text:
    """Build the cap-chip text for *limit*/*occupied* at *density*."""
    fault = accounting_valid is False
    estimate = source != "authoritative" and not fault and occupied is not None
    over = bool(over_limit) and not fault
    value_text = _value_text(limit, occupied, fault=fault, estimate=estimate)
    value_style = _agent_load_value_style(
        limit,
        occupied,
        dark=dark,
        fault=fault,
        over_limit=over,
    )
    text = Text()
    text.append(_cap_chrome(density, machine_label), style="dim")
    text.append(value_text, style=value_style)
    if override_active:
        text.append(
            _OVERRIDE_MARK,
            style=_override_mark_style(dark=dark, warning=override_warning),
        )
    if _is_stale(report_age_seconds) and not fault:
        age = max(0, int(report_age_seconds or 0))
        text.append(f" {_STALE_GLYPH}{age}s", style="dim")
    if fault:
        text.append(f" {_FAULT_MARK}", style=usage_rejected_style(dark=dark))
    if over:
        text.append(f" {_OVER_GLYPH}", style=value_style)
    text.append(_TRAILING_SEPARATOR, style="dim")
    return text


def _headline(
    limit: float,
    occupied: float | None,
    *,
    over_limit: bool | None,
) -> str:
    """Return the tooltip summary / headroom line."""
    if limit <= 0:
        return "Runner capacity has not loaded yet."
    if occupied is None:
        return f"cap unavailable · limit {_format_load_value(limit)}"
    load_text = _format_load_value(occupied)
    limit_text = _format_load_value(limit)
    if over_limit or round(occupied, 2) > round(limit, 2):
        over_text = _format_load_value(max(0.0, occupied - limit))
        return f"{load_text} of {limit_text} units in use · {over_text} over budget"
    free_text = _format_load_value(max(0.0, limit - occupied))
    return f"{load_text} of {limit_text} units in use · {free_text} headroom"


def _running_tooltip_line(
    running_nodes: int | None,
    holders: tuple[Any, ...],
    occupied: float | None,
) -> str | None:
    """Return the running-versus-cap line, or ``None`` when counts are unknown."""
    if running_nodes is None:
        return None
    holding = sum(
        1
        for holder in holders
        if not isinstance(getattr(holder, "weight", None), bool)
        and isinstance(getattr(holder, "weight", None), (int, float))
        and float(holder.weight) > 0
    )
    zero = sum(
        1
        for holder in holders
        if not isinstance(getattr(holder, "weight", None), bool)
        and isinstance(getattr(holder, "weight", None), (int, float))
        and float(holder.weight) <= 0
    )
    occupied_text = _format_load_value(occupied)
    return (
        f"{running_nodes} running nodes · {holding} hold capacity "
        f"({occupied_text}) · {zero} holds 0"
    )


def _holder_tooltip_block(holders: tuple[Any, ...]) -> list[str]:
    """Format the holder list, complete or explicitly truncated."""
    if not holders:
        return []
    lines = ["Held by:"]
    visible = list(holders[:_HOLDER_TOOLTIP_LIMIT])
    for holder in visible:
        label = str(getattr(holder, "label", "") or "")
        weight = _format_load_value(getattr(holder, "weight", None))
        kind = getattr(holder, "kind", None)
        suffix = f" ({kind})" if kind else ""
        lines.append(f"• {label}{suffix}: {weight}")
    remaining = len(holders) - len(visible)
    if remaining > 0:
        lines.append(f"… +{remaining} more")
    return lines


def _view_holder_lines(view: Any) -> list[str]:
    """Format charged claims from the shared capacity view model."""
    holdings = tuple(getattr(view, "charged", ()) or ())
    if not holdings:
        return []
    lines = ["Held by:"]
    visible = list(holdings[:_HOLDER_TOOLTIP_LIMIT])
    for row in visible:
        name = str(getattr(row, "name", "") or "")
        kind = getattr(row, "kind", None)
        weight = _format_load_value(getattr(row, "charged_weight", None))
        suffix = f" ({kind})" if kind else ""
        lines.append(f"• {name}{suffix}: {weight}")
    remaining = len(holdings) - len(visible)
    if remaining > 0:
        lines.append(f"… +{remaining} more")
    return lines


def _agent_load_tooltip(
    limit: float,
    occupied: float | None,
    holders: tuple[Any, ...] = (),
    *,
    source: str = "estimate",
    report_age_seconds: float | None = None,
    accounting_valid: bool | None = None,
    over_limit: bool | None = None,
    running_nodes: int | None = None,
    remote_tab: bool = False,
    known_occupied: float | None = None,
    diagnostics: tuple[str, ...] = (),
    report: Any | None = None,
) -> str:
    """Return the hover text for the cap chip."""
    if limit <= 0:
        return "Runner capacity has not loaded yet."
    view = None
    if report is not None:
        try:
            from sase.core.runner_slots import capacity_view

            view = capacity_view(report, running_nodes=running_nodes)
        except Exception:
            view = None
    lines: list[str] = []
    if view is not None:
        lines.append(view.headline)
        verdict = getattr(view, "verdict", None)
        if verdict is not None and getattr(verdict, "title", None):
            lines.append(str(verdict.title))
    else:
        lines.append(_headline(limit, occupied, over_limit=over_limit))
    running_line = None
    if view is not None and view.running_line:
        charged = _format_load_value(view.total_charged)
        running_line = view.running_line.replace(
            "holding capacity", f"hold capacity ({charged})"
        ).replace("holding 0", "holds 0")
    else:
        running_line = _running_tooltip_line(running_nodes, holders, occupied)
    if running_line:
        lines.append(running_line)
    if view is not None:
        lines.append(view.limit_line)
        lines.append(view.snapshot_line)
    elif source != "authoritative":
        lines.append("Roster estimate (authoritative report has not landed).")
    elif report_age_seconds is not None:
        lines.append(f"Snapshot age {max(0, int(report_age_seconds))}s")
    if accounting_valid is False:
        subtotal = known_occupied if known_occupied is not None else occupied
        if subtotal is not None:
            lines.append(f"Known subtotal: {_format_load_value(subtotal)}")
        if view is not None:
            lines.extend(view.diagnostics)
        else:
            lines.extend(diagnostics)
        lines.append("admission blocked")
    if view is not None and view.over_limit_note:
        lines.append(view.over_limit_note)
    elif over_limit:
        lines.append(
            "Over the default limit: admitted under per-launch "
            "%queue(capacity=N) budgets."
        )
    if view is not None:
        lines.extend(_view_holder_lines(view))
        zero_weight = tuple(getattr(view, "zero_weight", ()) or ())
        if zero_weight:
            lines.append(f"+{len(zero_weight)} at zero weight")
    else:
        lines.extend(_holder_tooltip_block(holders))
    lines.append(_INSPECTOR_HINT)
    if remote_tab:
        lines.append(_REMOTE_NOTE)
    return "\n".join(line for line in lines if line)


class AgentLoadIndicator(Static):
    """Right-side machine-labelled cap chip for the Agents status row.

    A render-only view: callers drive it with :meth:`update_load` and the
    hosting :class:`AgentInfoRow` drives density with :meth:`set_density`.
    """

    def __init__(
        self, *args: Any, density: AgentLoadDensity = "full", **kwargs: Any
    ) -> None:
        self._limit = 0.0
        self._occupied: float | None = None
        self._holders: tuple[Any, ...] = ()
        self._source = "estimate"
        self._report_age_seconds: float | None = None
        self._accounting_valid: bool | None = None
        self._over_limit: bool | None = None
        self._scan_current: bool | None = None
        self._limit_provenance: Any | None = None
        self._machine_label = _resolve_machine_label()
        self._override_active = False
        self._override_warning = False
        self._running_nodes: int | None = None
        self._remote_tab = False
        self._known_occupied: float | None = None
        self._diagnostics: tuple[str, ...] = ()
        self._report: Any | None = None
        self._report_key: tuple[Any, ...] | None = None
        self._density: AgentLoadDensity = density
        super().__init__(
            _build_agent_load_text(
                0.0,
                None,
                dark=True,
                density=density,
                machine_label=self._machine_label,
            ),
            *args,
            **kwargs,
        )
        self.tooltip = _agent_load_tooltip(0.0, None)

    @property
    def density(self) -> AgentLoadDensity:
        """Return the currently rendered density."""

        return self._density

    @property
    def full_cells(self) -> int:
        """Return the cell width of the full chip as currently resolved."""

        return cell_len(self._text_for_density("full").plain)

    @property
    def compact_cells(self) -> int:
        """Return the cell width of the compact chip as currently resolved."""

        return cell_len(self._text_for_density("compact").plain)

    @property
    def content_cells(self) -> int:
        """Return the cell width of the chip at the current density."""

        if self._density == "compact":
            return self.compact_cells
        return self.full_cells

    @property
    def running_nodes(self) -> int | None:
        """Return the Running-bucket count supplied by the Agents display."""
        return self._running_nodes

    def on_click(self, event: events.Click) -> None:
        """Open the detailed capacity view from the machine's cap chip."""
        if event.button != 1:
            return
        event.stop()
        action = getattr(self.app, "action_show_capacity_inspector", None)
        if callable(action):
            action()

    def update_load(
        self,
        limit: float,
        occupied: float | None,
        holders: tuple[Any, ...] = (),
        *,
        source: str = "estimate",
        report_age_seconds: float | None = None,
        accounting_valid: bool | None = None,
        over_limit: bool | None = None,
        scan_current: bool | None = None,
        limit_provenance: Any | None = None,
        machine_label: str | None = None,
        running_nodes: int | None = None,
        remote_tab: bool = False,
        known_occupied: float | None = None,
        diagnostics: tuple[str, ...] = (),
        report: Any | None = None,
        now: float | None = None,
    ) -> None:
        """Render *limit*/*occupied*, refitting the host row on width change.

        A no-op when nothing changed, so countdown ticks cost nothing.
        """

        holders = tuple(holders)
        diagnostics = tuple(diagnostics)
        age = (
            None
            if report_age_seconds is None
            else float(max(0, int(report_age_seconds)))
        )
        label = (
            machine_label.strip()
            if isinstance(machine_label, str) and machine_label.strip()
            else _resolve_machine_label()
        )
        moment = time.time() if now is None else now
        override_active, override_warning = _override_marks(
            limit_provenance, now=moment
        )
        report_key = None
        if report is not None:
            report_key = (
                getattr(report, "token", None),
                getattr(report, "computed_at", None),
            )
        if (
            limit == self._limit
            and occupied == self._occupied
            and holders == self._holders
            and source == self._source
            and age == self._report_age_seconds
            and accounting_valid == self._accounting_valid
            and over_limit == self._over_limit
            and scan_current == self._scan_current
            and limit_provenance == self._limit_provenance
            and label == self._machine_label
            and override_active == self._override_active
            and override_warning == self._override_warning
            and running_nodes == self._running_nodes
            and remote_tab == self._remote_tab
            and known_occupied == self._known_occupied
            and diagnostics == self._diagnostics
            and report_key == self._report_key
        ):
            return
        old_width = self.content_cells
        self._limit = limit
        self._occupied = occupied
        self._holders = holders
        self._source = source
        self._report_age_seconds = age
        self._accounting_valid = accounting_valid
        self._over_limit = over_limit
        self._scan_current = scan_current
        self._limit_provenance = limit_provenance
        self._machine_label = label
        self._override_active = override_active
        self._override_warning = override_warning
        self._running_nodes = running_nodes
        self._remote_tab = remote_tab
        self._known_occupied = known_occupied
        self._diagnostics = diagnostics
        self._report = report
        self._report_key = report_key
        self._apply_content()
        if self.content_cells != old_width:
            self._request_host_fit()

    def set_density(self, density: AgentLoadDensity) -> bool:
        """Render *density*, returning True only when it actually changed."""

        if density == self._density:
            return False
        self._density = density
        self._apply_content()
        return True

    def on_mount(self) -> None:
        """Watch the theme and paint the current load state."""

        self.watch(self.app, "theme", self._app_theme_changed, init=False)
        self._apply_content()

    def _app_theme_changed(self) -> None:
        """Repaint chip colors after an app theme switch."""

        if self.is_mounted:
            self._apply_content()

    def _current_dark_theme(self) -> bool:
        """Return whether the active app theme is dark, defaulting to dark."""

        try:
            return bool(self.app.current_theme.dark)
        except Exception:
            return True

    def _text_for_density(self, density: AgentLoadDensity) -> Text:
        """Build chip text at *density* from the cached load state."""

        try:
            dark = self._current_dark_theme()
        except Exception:
            dark = True
        return _build_agent_load_text(
            self._limit,
            self._occupied,
            dark=dark,
            density=density,
            machine_label=self._machine_label,
            source=self._source,
            report_age_seconds=self._report_age_seconds,
            accounting_valid=self._accounting_valid,
            over_limit=self._over_limit,
            override_active=self._override_active,
            override_warning=self._override_warning,
        )

    def _apply_content(self) -> None:
        """Update content and tooltip from the cached load state."""

        content = self._text_for_density(self._density)
        self.update(content)
        tooltip = _agent_load_tooltip(
            self._limit,
            self._occupied,
            self._holders,
            source=self._source,
            report_age_seconds=self._report_age_seconds,
            accounting_valid=self._accounting_valid,
            over_limit=self._over_limit,
            running_nodes=self._running_nodes,
            remote_tab=self._remote_tab,
            known_occupied=self._known_occupied,
            diagnostics=self._diagnostics,
            report=self._report,
        )
        if self.tooltip != tooltip:
            self.tooltip = tooltip

    def _request_host_fit(self) -> None:
        """Ask the hosting status row to recompute free cells and density."""

        node = self.parent
        while node is not None:
            fit = getattr(node, "fit_launch_context_bar", None)
            if callable(fit):
                fit()
                return
            node = node.parent


__all__ = [
    "AgentLoadDensity",
    "AgentLoadIndicator",
]
