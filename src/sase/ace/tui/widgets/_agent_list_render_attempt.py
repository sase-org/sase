"""Prior-attempt row rendering — one ``↳ Attempt N`` row per retry record."""

from rich.text import Text

from ..models.agent import Agent, AttemptRecord
from ._agent_list_render_layout import build_attempt_runtime_suffix


def format_attempt_option(
    agent: Agent,
    record: AttemptRecord,
    *,
    is_selected: bool,
) -> tuple[Text, Text, str]:
    """Build ``(left_text, suffix_text, option_id)`` parts for a prior-attempt row."""
    text = Text()
    text.append("    ↳ ", style="dim #808080")
    label_style = "bold #FF8700" if is_selected else "#FF8700"
    text.append(f"Attempt {record.attempt_number}", style=label_style)
    try:
        hhmmss = record.start_hhmmss
    except (ValueError, OSError):
        hhmmss = "??:??:??"
    text.append(f" · {hhmmss}", style="dim #FF8700")
    if record.used_fallback:
        text.append(" (fallback)", style="dim #FF8700")
    text.append(f" · {record.status}", style="dim #FF8700")
    if record.error_snippet:
        text.append(f": {record.error_snippet}", style="dim italic #FF5F5F")
    suffix = build_attempt_runtime_suffix(record)
    option_id = f"attempt:{agent.raw_suffix}:{record.attempt_number}"
    return text, suffix, option_id
