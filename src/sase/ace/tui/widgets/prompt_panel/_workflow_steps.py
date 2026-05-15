"""Rich text formatting for workflow step lists."""

from typing import Any

from rich.text import Text

from ._helpers import format_output, get_rich_status_indicator
from ._workflow_types import EmbeddedMarkerMap, EmbeddedMetaMap

# Display width for step header lines (name + status)
_STEP_LINE_WIDTH = 60

# Box drawing characters for embedded workflow sections
_BOX_TOP_LEFT = "\u250c"
_BOX_VERTICAL = "\u2502"
_BOX_BOTTOM_LEFT = "\u2514"
_BOX_HORIZONTAL = "\u2500"
_BOX_SEPARATOR = "\u2504"  # ┄ (dotted)

# Phase indicators
_PRE_ARROW = "\u25b2"  # ▲
_POST_ARROW = "\u25bc"  # ▼

# Style constants
_BORDER_STYLE = "#5F87AF"
_PRE_STYLE = "bold #5F87AF"
_POST_STYLE = "bold #D7AF5F"
_WORKFLOW_NAME_STYLE = "bold #AF87D7"
_STEP_NUM_STYLE = "bold #87D7FF"
_STEP_NAME_STYLE = "bold #AF87D7"


def format_workflow_steps_rich(
    steps: list[dict[str, Any]],
    embedded_markers: EmbeddedMarkerMap,
    embedded_meta: EmbeddedMetaMap,
) -> Text:
    """Build a rich Text renderable for all workflow steps.

    Args:
        steps: List of step state dicts from workflow_state.json.
        embedded_markers: Embedded step markers grouped by parent_step_index.
        embedded_meta: Embedded workflow metadata grouped by step_name.

    Returns:
        Rich Text renderable.
    """
    text = Text()
    total_steps = len(steps)

    for i, step in enumerate(steps):
        step_name = step.get("name", "unknown")
        status = step.get("status", "pending")
        output = step.get("output")
        error = step.get("error")
        tb = step.get("traceback")

        # Step header line: "Step 1/6 ─ setup ─────────── ✓ completed"
        _render_step_header(text, i, total_steps, step_name, status)

        # Separator line
        text.append(
            "  " + _BOX_HORIZONTAL * _STEP_LINE_WIDTH + "\n", style=_BORDER_STYLE
        )

        # Embedded workflow sections (if any)
        markers = embedded_markers.get(i, [])
        meta_list = embedded_meta.get(step_name, [])
        if markers:
            text.append("\n")
            _render_embedded_sections(text, markers, meta_list)

        # Error (if any)
        if error:
            text.append("    Error: ", style="bold #FF5F5F")
            text.append(f"{error}\n", style="#FF5F5F")

        # Traceback (if any)
        if tb:
            text.append("    Traceback:\n", style="bold #FF5F5F")
            for line in tb.splitlines():
                text.append(f"      {line}\n", style="dim")

        # Output (if any)
        if output:
            output_str = format_output(output)
            text.append("    Output:\n", style="dim")
            for line in output_str.splitlines():
                text.append(f"      {line}\n", style="dim")

        text.append("\n")

    return text


def _render_step_header(
    text: Text,
    index: int,
    total: int,
    name: str,
    status: str,
) -> None:
    """Render a step header line into a Text object.

    Format: "  Step 1/6 ─ setup ─────────────────── ✓ completed"

    Args:
        text: Text object to append to.
        index: 0-based step index.
        total: Total number of steps.
        name: Step name.
        status: Step status string.
    """
    text.append("  Step ", style=_STEP_NUM_STYLE)
    text.append(f"{index + 1}/{total}", style=_STEP_NUM_STYLE)
    text.append(f" {_BOX_HORIZONTAL} ", style=_BORDER_STYLE)
    text.append(name, style=_STEP_NAME_STYLE)
    text.append(" ", style="")

    # Status symbol + label at the right
    symbol, style = get_rich_status_indicator(status)
    status_label = f"{symbol} {status}"

    # Fill with ─ between name and status
    # Calculate used width: "  Step X/Y ─ {name} " + status_label
    prefix_len = len(f"  Step {index + 1}/{total} {_BOX_HORIZONTAL} {name} ")
    fill_len = max(1, _STEP_LINE_WIDTH + 2 - prefix_len - len(status_label))
    text.append(_BOX_HORIZONTAL * fill_len + " ", style=_BORDER_STYLE)
    text.append(f"{status_label}\n", style=style)


def _render_embedded_sections(
    text: Text,
    markers: list[dict[str, Any]],
    meta_list: list[dict[str, Any]],
) -> None:
    """Render boxed embedded workflow sections into a Text object.

    Groups markers by embedded_workflow_name, then renders each group
    as a bordered box with PRE/POST labels.

    Args:
        text: Text object to append to.
        markers: List of embedded step marker dicts (sorted by step_index).
        meta_list: List of embedded workflow metadata dicts for display names.
    """
    # Build a lookup for workflow display names from metadata
    meta_lookup: dict[str, str] = {}
    for meta in meta_list:
        wf_name = meta.get("name", "")
        args = meta.get("args", {})
        args = {k: v for k, v in args.items() if v != ""}
        if args:
            args_str = ", ".join(f"{k}={v}" for k, v in args.items())
            meta_lookup[wf_name] = f"#{wf_name}({args_str})"
        else:
            meta_lookup[wf_name] = f"#{wf_name}"

    # Group markers by embedded_workflow_name, preserving order
    groups: list[tuple[str, list[dict[str, Any]]]] = []
    seen: dict[str, int] = {}
    for marker in markers:
        wf_name = marker.get("embedded_workflow_name", "")
        if not wf_name:
            continue
        if wf_name in seen:
            groups[seen[wf_name]][1].append(marker)
        else:
            seen[wf_name] = len(groups)
            groups.append((wf_name, [marker]))

    box_width = _STEP_LINE_WIDTH - 4  # indent is "    "

    for wf_name, group_markers in groups:
        display_name = meta_lookup.get(wf_name, f"#{wf_name}")

        # Top border: ┌─ #workflow_name ─────────────
        text.append(f"    {_BOX_TOP_LEFT}{_BOX_HORIZONTAL} ", style=_BORDER_STYLE)
        text.append(display_name, style=_WORKFLOW_NAME_STYLE)
        text.append(" ", style="")
        name_len = len(f"{_BOX_TOP_LEFT}{_BOX_HORIZONTAL} {display_name} ")
        fill = max(1, box_width - name_len)
        text.append(_BOX_HORIZONTAL * fill + "\n", style=_BORDER_STYLE)

        # Separate into pre and post steps
        pre_steps = [m for m in group_markers if m.get("is_pre_prompt_step", False)]
        post_steps = [
            m for m in group_markers if not m.get("is_pre_prompt_step", False)
        ]

        # Render PRE steps
        for marker in pre_steps:
            _render_embedded_step_line(text, marker, is_pre=True)

        # Separator between pre and post (if both exist)
        if pre_steps and post_steps:
            text.append(f"    {_BOX_VERTICAL}  ", style=_BORDER_STYLE)
            text.append(_BOX_SEPARATOR * (box_width - 3) + "\n", style="dim")

        # Render POST steps
        for marker in post_steps:
            _render_embedded_step_line(text, marker, is_pre=False)

        # Bottom border: └──────────────────────────
        text.append(f"    {_BOX_BOTTOM_LEFT}", style=_BORDER_STYLE)
        text.append(_BOX_HORIZONTAL * (box_width - 1) + "\n", style=_BORDER_STYLE)
        text.append("\n")


def _render_embedded_step_line(
    text: Text, marker: dict[str, Any], *, is_pre: bool
) -> None:
    """Render a single embedded step line with phase and status.

    Format: "    │  ▲ PRE   step_name              ✓ completed"

    Args:
        text: Text object to append to.
        marker: The embedded step marker dict.
        is_pre: Whether this is a pre-prompt step.
    """
    step_name = marker.get("step_name", "unknown")
    status = marker.get("status", "pending")

    # Left border
    text.append(f"    {_BOX_VERTICAL}  ", style=_BORDER_STYLE)

    # Phase arrow and label
    if is_pre:
        text.append(f"{_PRE_ARROW} PRE   ", style=_PRE_STYLE)
    else:
        text.append(f"{_POST_ARROW} POST  ", style=_POST_STYLE)

    # Step name (left-aligned with padding)
    name_col_width = 30
    padded_name = step_name.ljust(name_col_width)
    text.append(padded_name, style="")

    # Status
    symbol, style = get_rich_status_indicator(status)
    text.append(f"{symbol} {status}\n", style=style)
