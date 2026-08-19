"""Helper functions for the agent prompt panel widget."""

import json
import re
from pathlib import Path
from typing import Any

from rich.cells import cell_len
from rich.style import Style
from rich.style import StyleType
from rich.text import Text

from sase.llm_provider.model_label import append_model_field as append_model_field

from ...models.agent import Agent
from ._section_navigation import SECTION_MARKER_META_KEY

# Shared prose measure for prompt-panel lanes: the strict total rendered-cell
# budget for a wrapped line, including any leading indentation or prefix.
PROMPT_PANEL_LINE_CELL_LIMIT = 80


def get_rich_status_indicator(status: str) -> tuple[str, str]:
    """Get a status indicator symbol and Rich style string.

    Args:
        status: The status string (e.g. "completed", "failed").

    Returns:
        A (symbol, style) tuple for use with Rich Text.
    """
    indicators: dict[str, tuple[str, str]] = {
        "completed": ("\u2713", "bold #5FD75F"),
        "failed": ("\u2717", "bold #FF5F5F"),
        "in_progress": ("\u25cc", "bold #87D7FF"),
        "pending": ("\u25cb", "dim"),
        "waiting_hitl": ("\u25c8", "bold #FFAF5F"),
        "skipped": ("\u2298", "dim"),
    }
    return indicators.get(status, ("?", "dim"))


def format_output(output: Any) -> str:
    """Format step output for display.

    Args:
        output: The output data (dict, list, or primitive).

    Returns:
        Formatted string representation.
    """
    if output is None:
        return "(none)"

    if isinstance(output, dict):
        # Unwrap _data or _raw if present
        display_data = output.get("_data", output.get("_raw", output))
        if isinstance(display_data, str):
            return display_data
        try:
            return json.dumps(display_data, indent=2, default=str)
        except Exception:
            return str(display_data)
    elif isinstance(output, list):
        try:
            return json.dumps(output, indent=2, default=str)
        except Exception:
            return str(output)
    else:
        return str(output)


def format_meta_key(key: str) -> str:
    """Format a meta_* key for display.

    Strips the 'meta_' prefix, replaces underscores with spaces, and
    title-cases the result.

    Args:
        key: The raw meta key (e.g. 'meta_new_cl').

    Returns:
        Formatted display name (e.g. 'New Cl').
    """
    return key.removeprefix("meta_").replace("_", " ").title()


SPECIAL_META_KEYS = frozenset(
    {
        "meta_project",
        "meta_patch",
        "meta_changespec",  # legacy compatibility alias
        "meta_workspace",
    }
)
COMMIT_META_KEYS = frozenset(
    {"meta_commit_message", "meta_new_commit", "meta_commit_cwd", "meta_commits"}
)
WORKFLOW_VARIABLES_SECTION_LABEL = "WORKFLOW VARIABLES"
_MAJOR_SECTION_RULE = "\u2500" * 50
PROMPT_PANEL_SECTION_HEADING_STYLE = "bold #D7AF5F underline"


def append_major_section_divider(text: Text) -> None:
    """Append the standard prompt-panel major-section divider."""
    text.append("\n")
    text.append(_MAJOR_SECTION_RULE + "\n", style="dim")
    text.append("\n")


def append_section_heading(
    text: Any,
    heading: str | Text,
    *,
    style: StyleType = PROMPT_PANEL_SECTION_HEADING_STYLE,
    section_id: str | None = None,
) -> None:
    """Append one prompt-panel heading followed by exactly one line ending.

    ``Text`` renderables add their ``end`` value when Rich renders them inside a
    ``Group``.  Standalone heading chunks already contain the explicit newline
    appended here, so suppress that implicit ending to keep the first content
    row directly beneath the heading.
    """
    heading_plain = heading.plain if isinstance(heading, Text) else heading
    start = len(text.plain)
    if isinstance(heading, Text):
        text.append_text(heading)
    else:
        text.append(heading, style=style)
    _mark_section_heading(
        text,
        section_id or _default_section_id(heading_plain),
        start=start,
        end=start + len(heading_plain),
    )
    text.append("\n")
    text.end = ""


def append_kind_header(text: Text, label: str, color: str) -> None:
    """Append a kind identity line that is header chrome, not a section title.

    The underline is one span, including any spaces in ``label``. Do not route
    kind labels through :func:`append_section_heading`; that would steal the
    first ``Ctrl+J`` jump from the first real section.
    """
    text.append(f"{label}\n", style=f"bold {color} underline")


def _mark_section_heading(
    text: Any,
    section_id: str,
    *,
    start: int,
    end: int,
) -> None:
    """Attach a non-visual semantic identity to a rendered title span."""
    if start >= end:
        return
    text.stylize(
        Style(meta={SECTION_MARKER_META_KEY: section_id}),
        start,
        end,
    )


def _default_section_id(heading: str) -> str:
    """Return a stable identity for headings without a dynamic override."""
    semantic_label = heading.split(" · ", 1)[0].strip().rstrip(":")
    return re.sub(r"[^a-z0-9]+", "-", semantic_label.lower()).strip("-")


def _split_token_by_cells(token: str, width: int) -> tuple[str, str]:
    """Split ``token`` into a head fitting ``width`` cells and the remainder.

    The head always contains at least one character so wrapping makes progress
    even if a single glyph is wider than ``width``.
    """
    head = ""
    head_cells = 0
    for index, char in enumerate(token):
        char_cells = cell_len(char)
        if head and head_cells + char_cells > width:
            return head, token[index:]
        head += char
        head_cells += char_cells
    return token, ""


def wrap_text_by_cells(text: str, width: int) -> list[str]:
    """Wrap normalized prose so each line fits within ``width`` cells.

    Breaks on whitespace when possible and never on hyphens. A token wider than
    ``width`` is hard-split by cells so the strict column budget always holds.
    """
    lines: list[str] = []
    current = ""
    for word in text.split():
        while cell_len(word) > width:
            if current:
                lines.append(current)
                current = ""
            head, word = _split_token_by_cells(word, width)
            lines.append(head)
        if not current:
            current = word
        elif cell_len(current) + 1 + cell_len(word) <= width:
            current = f"{current} {word}"
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def extract_meta_fields(output: dict[str, Any]) -> list[tuple[str, str]]:
    """Extract meta_* fields from a step output dict.

    Excludes special meta keys (meta_project, meta_patch, meta_workspace)
    that are rendered in the header section instead.

    Args:
        output: A step output dictionary.

    Returns:
        List of (display_name, value) tuples for meta fields.
    """
    results: list[tuple[str, str]] = []
    for key, value in output.items():
        if (
            key.startswith("meta_")
            and key not in SPECIAL_META_KEYS
            and key not in COMMIT_META_KEYS
        ):
            results.append((format_meta_key(key), str(value)))
    return results


def aggregate_meta_fields(
    steps: list[dict[str, Any]],
) -> list[tuple[str, str]]:
    """Aggregate meta_* fields from all workflow steps.

    If a raw key appears in more than one step, each occurrence gets a
    ' #N' suffix (N starting at 1).

    Args:
        steps: List of step state dicts (each may have an 'output' dict).

    Returns:
        List of (display_name, value) tuples.
    """
    # First pass: collect all (raw_key, display_name, value) triples and count keys
    entries: list[tuple[str, str, str]] = []
    key_counts: dict[str, int] = {}
    for step in steps:
        output = step.get("output")
        if not isinstance(output, dict):
            continue
        for key, value in output.items():
            if key.startswith("meta_") and key not in SPECIAL_META_KEYS:
                key_counts[key] = key_counts.get(key, 0) + 1
                entries.append((key, format_meta_key(key), str(value)))

    # Second pass: build results, adding #N suffix for duplicates
    counters: dict[str, int] = {}
    results: list[tuple[str, str]] = []
    for raw_key, display_name, value in entries:
        if key_counts[raw_key] > 1:
            counters[raw_key] = counters.get(raw_key, 0) + 1
            display_name = f"{display_name} #{counters[raw_key]}"
        results.append((display_name, value))
    return results


def should_render_agent_detail_model(agent: Agent) -> bool:
    """Return whether the agent detail header should show model metadata."""
    return not (agent.is_workflow_child and not agent.is_agent_entry)


def project_display_label(agent: Agent, fallback: object) -> str:
    """Return the display label for an agent's project field."""
    return agent.project_display_name or str(fallback)


def load_xprompts_used(agent: Agent) -> list[dict[str, Any]] | None:
    """Load xprompt metadata from xprompts.json.

    Uses the step-specific file ``xprompts_{step_name}.json``
    when the agent has a ``step_name``; falls back to the shared file
    only when ``step_name`` is None.

    Args:
        agent: The agent to load metadata for.

    Returns:
        List of workflow metadata dicts, or None if not found.
    """
    artifacts_dir = agent.get_artifacts_dir()
    if artifacts_dir is None:
        return None

    artifacts_path = Path(artifacts_dir)

    # Try step-specific file first (multi-step workflows)
    if agent.step_name:
        step_file = artifacts_path / f"xprompts_{agent.step_name}.json"
        if step_file.exists():
            try:
                with open(step_file, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list) and data:
                    return data
            except Exception:
                pass
        # Step has no xprompts — don't fall back to shared file
        return None

    # Fall back to shared file (only for agents without step_name)
    metadata_file = artifacts_path / "xprompts.json"
    if not metadata_file.exists():
        return None

    try:
        with open(metadata_file, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None

    if not isinstance(data, list) or not data:
        return None

    return data
