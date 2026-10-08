"""Branch control buttons, labels, and layout for the gate branch controls.

The controls a reviewer presses — one button per single-option branch, the
toggles inside an AND group, and that group's own submit — are a pure function
of the branch being rendered. Keeping them here leaves
:class:`~sase.ace.tui.modals.gate_branch_controls.GateBranchControls` to own
selection state, feedback, and submission.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button

from sase.notification_gates.models import GateGroup, GateOption

from .gate_input_panel_model import (
    DEFAULT_HOST_COLLECTED_PROPERTIES,
    option_declared_input_count,
    option_input_count_label,
)


class GateControlButton(Button):
    """Button carrying its source branch for focus-driven feedback state."""

    class ControlFocused(Message):
        def __init__(self, branch_index: int) -> None:
            super().__init__()
            self.branch_index = branch_index

    def __init__(self, *args: object, branch_index: int, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.branch_index = branch_index

    def on_focus(self) -> None:
        self.post_message(self.ControlFocused(self.branch_index))


def _option_label(option: GateOption) -> str:
    """The option's icon and label, safe to render as Rich markup."""
    value = f"{option.icon} {option.label}" if option.icon else option.label
    return escape(value)


def _input_badge_markup(
    option: GateOption,
    host_collected_properties: Collection[str],
) -> str:
    """Dim ``✎ n inputs`` suffix, or empty when the option declares none."""
    label = option_input_count_label(
        option_declared_input_count(option, host_collected_properties)
    )
    return f"[dim]{label}[/dim]" if label else ""


def _option_control_label(
    option: GateOption,
    host_collected_properties: Collection[str],
) -> str:
    """Icon, escaped label, and an input-count badge when the option has inputs."""
    label = _option_label(option)
    badge = _input_badge_markup(option, host_collected_properties)
    return f"{label} {badge}" if badge else label


def toggle_label(
    option: GateOption,
    selected: bool,
    host_collected_properties: Collection[str] = DEFAULT_HOST_COLLECTED_PROPERTIES,
) -> str:
    """An AND member's label, prefixed by its checkbox state."""
    return (
        f"{'☑️' if selected else '⬜'} "
        f"{_option_control_label(option, host_collected_properties)}"
    )


def _plan_short_toggle_text(option_id: str) -> str:
    """Short Tale toggle text for the compact plan Verdict (no checkbox)."""
    if option_id == "approve":
        return "🚀 Launch coder"
    if option_id == "commit":
        return "💾 Commit plan"
    return option_id


def plan_toggle_label(
    option: GateOption,
    selected: bool,
    host_collected_properties: Collection[str] = DEFAULT_HOST_COLLECTED_PROPERTIES,
) -> str:
    """Plan-review AND toggle with short labels; generic gates keep full labels."""
    if option.id in ("approve", "commit"):
        short = _plan_short_toggle_text(option.id)
        badge = _input_badge_markup(option, host_collected_properties)
        base = f"{'☑️' if selected else '⬜'} {short}"
        return f"{base} {badge}" if badge else base
    return toggle_label(option, selected, host_collected_properties)


def plan_branch_submit_text(
    branch_index: int,
    branch: Sequence[str],
    options_by_id: dict[str, GateOption],
    group_label: str | None = None,
) -> str:
    """Numbered compact submit text for one plan branch."""
    number = branch_index + 1
    if len(branch) > 1:
        # Tale AND submit.
        return f"{number} ✅ Tale"
    option_id = branch[0]
    if option_id == "approve" and group_label is None:
        # Epic approve (no commit option in gate).
        return f"{number} ✅ Epic"
    if option_id == "reject":
        return f"{number} ❌ Reject"
    if option_id == "feedback":
        return f"{number} 💬 Feedback"
    option = options_by_id.get(option_id)
    label = option.label if option is not None else option_id
    icon = option.icon if option is not None and option.icon else ""
    text = f"{icon} {label}".strip() if icon else label
    return f"{number} {text}"


def _group_label(group: GateGroup) -> str:
    """The group's icon and label, safe to render as Rich markup."""
    value = f"{group.icon} {group.label}" if group.icon else str(group.label)
    return escape(value)


def _numbered_label(branch_index: int, label: str) -> str:
    """*label* prefixed by the one-based number that submits its branch."""
    return f"{branch_index + 1} {label}"


def compose_singleton_row(
    branch_indices: Sequence[int],
    options: Sequence[GateOption],
    *,
    primary_branch_index: int,
    host_collected_properties: Collection[str] = DEFAULT_HOST_COLLECTED_PROPERTIES,
) -> ComposeResult:
    """Render a run of adjacent single-option branches as one row."""
    with Horizontal(classes="gate-singleton-row"):
        for index, option in zip(branch_indices, options, strict=True):
            primary = index == primary_branch_index
            yield GateControlButton(
                _numbered_label(
                    index,
                    _option_control_label(option, host_collected_properties),
                ),
                branch_index=index,
                id=f"gate-singleton-{index}",
                classes="gate-singleton gate-primary" if primary else "gate-singleton",
                variant="success" if primary else "default",
            )


def compose_group(
    branch_index: int,
    options: Sequence[GateOption],
    group: GateGroup,
    *,
    expanded: bool,
    primary: bool,
    selected: Collection[str],
    host_collected_properties: Collection[str] = DEFAULT_HOST_COLLECTED_PROPERTIES,
) -> ComposeResult:
    """Render one AND branch: its collapsed header, toggles, and submit."""
    label = _numbered_label(branch_index, _group_label(group))
    with Vertical(classes="gate-group", id=f"gate-group-{branch_index}"):
        yield GateControlButton(
            label,
            branch_index=branch_index,
            id=f"gate-group-expand-{branch_index}",
            classes="gate-group-expand hidden" if expanded else "gate-group-expand",
        )
        with Vertical(
            id=f"gate-group-details-{branch_index}",
            classes="gate-group-details" if expanded else "gate-group-details hidden",
        ):
            for option_index, option in enumerate(options):
                yield GateControlButton(
                    toggle_label(
                        option,
                        option.id in selected,
                        host_collected_properties,
                    ),
                    branch_index=branch_index,
                    id=f"gate-option-{branch_index}-{option_index}",
                    classes="gate-option-toggle",
                )
            yield GateControlButton(
                label,
                branch_index=branch_index,
                id=f"gate-group-submit-{branch_index}",
                classes=(
                    "gate-group-submit gate-primary" if primary else "gate-group-submit"
                ),
                variant="success" if primary else "default",
                disabled=not selected,
            )


def parse_option_control_id(control_id: str) -> tuple[int, int] | None:
    """The (branch, option) indices behind a ``gate-option-`` control id."""
    if not control_id.startswith("gate-option-"):
        return None
    _prefix, _gate, branch_value, option_value = control_id.split("-")
    return int(branch_value), int(option_value)


__all__ = [
    "GateControlButton",
    "compose_group",
    "compose_singleton_row",
    "parse_option_control_id",
    "plan_branch_submit_text",
    "plan_toggle_label",
    "toggle_label",
]
