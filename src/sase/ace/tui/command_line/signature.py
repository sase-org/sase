"""Live signature line for the ``:`` Command Line panel.

Renders the Rust resolver's signature segments with the active slot
emphasized, swaps in the highlighted option's summary (choices, default,
repeatable/mutex notes) while the popup menu has a highlight, shows the
first advisory diagnostic message, and appends the right-aligned policy
chips (``⚠ writes``, ``↗ terminal``, ``⊘ not runnable``,
``asks to confirm · -y``, ``reads stdin``).

All renderers are pure functions over the resolver dicts, so the panel
and the tests share the same code path.
"""

from __future__ import annotations

from typing import Any

from rich.text import Text

__all__ = [
    "build_chips",
    "build_signature",
    "first_diagnostic_message",
    "option_summary_text",
    "role_style",
    "signature_hint_line",
]

#: Token-role colors from the panel visual language.
_ROLE_STYLES = {
    "command": "bold #00D7AF",
    "subcommand": "bold #00D7AF",
    "option": "#87D7FF",
    "option_name": "#87D7FF",
    "quoted": "#FFB86B",
    "string": "#FFB86B",
}


def role_style(role: str) -> str:
    """Return the highlight style for a resolver token *role*."""
    return _ROLE_STYLES.get(role, "")


def first_diagnostic_message(context: dict[str, Any] | None) -> str:
    """Return the first advisory diagnostic message, or ``""``."""
    if not context:
        return ""
    diagnostics = context.get("diagnostics") or []
    if not diagnostics:
        return ""
    return str(diagnostics[0].get("message", "") or "")


def build_signature(context: dict[str, Any] | None) -> Text:
    """Render the live signature with the active slot emphasized."""
    text = Text()
    if not context:
        return text
    signature = context.get("signature") or {}
    segments = signature.get("segments") or []
    for index, segment in enumerate(segments):
        if index:
            text.append(" ")
        label = str(segment.get("text", "") or "")
        if segment.get("active"):
            text.append(label, style="bold reverse")
        elif segment.get("required"):
            text.append(label, style="bold")
        else:
            text.append(label, style="dim")
    return text


def option_summary_text(help_option: dict[str, Any] | None) -> str:
    """Render the popup-highlighted option's summary row, or ``""``."""
    if not help_option:
        return ""
    parts = [str(help_option.get("summary", "") or "")]
    choices = help_option.get("choices") or []
    if choices:
        parts.append("choices: " + ", ".join(str(choice) for choice in choices))
    default = help_option.get("default")
    if default is not None:
        parts.append(f"default: {default}")
    notes: list[str] = []
    if help_option.get("repeatable"):
        notes.append("repeatable")
    if help_option.get("mutex"):
        notes.append(f"mutex: {help_option.get('mutex')}")
    if notes:
        parts.append("(" + ", ".join(notes) + ")")
    return " · ".join(part for part in parts if part)


def build_chips(context: dict[str, Any] | None) -> Text:
    """Render the right-aligned policy chips for the signature row."""
    text = Text()
    if not context:
        return text

    def _chip(label: str, style: str) -> None:
        if len(text):
            text.append("  ")
        text.append(label, style=style)

    run_policy = context.get("run_policy") or {}
    policy = str(run_policy.get("policy", "") or "proc")
    if context.get("writes"):
        _chip("⚠ writes", "dim amber")
    if policy == "foreground":
        _chip("↗ terminal", "dim")
    elif policy == "deny":
        note = str(run_policy.get("note", "") or "not runnable")
        _chip(f"⊘ {note}", "dim red")
    if context.get("confirms") and not context.get("confirm_flag_present"):
        _chip("asks to confirm · -y", "dim")
    if context.get("stdin"):
        _chip("reads stdin", "dim")
    return text


def signature_hint_line(
    context: dict[str, Any] | None,
    *,
    highlighted_option: dict[str, Any] | None = None,
) -> Text:
    """Render the full signature/hint row: signature, diagnostic, chips.

    While the popup highlights an option, its summary swaps in for the
    slot signature. Otherwise the first advisory diagnostic follows the
    signature in red. Policy chips trail on the right.
    """
    if highlighted_option is not None:
        summary = option_summary_text(highlighted_option)
        if summary:
            return Text(summary, style="dim")
    text = build_signature(context)
    diagnostic = first_diagnostic_message(context)
    if diagnostic:
        if len(text):
            text.append("  ")
        text.append(diagnostic, style="red")
    chips = build_chips(context)
    if len(chips):
        if len(text):
            text.append("   ")
        text.append_text(chips)
    return text
