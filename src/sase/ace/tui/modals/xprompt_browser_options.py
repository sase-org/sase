"""Option-list rendering helpers for the XPrompt browser pane."""

from __future__ import annotations

from rich.text import Text
from textual.widgets.option_list import Option

from sase.xprompt.reference_display import workflow_reference_prefix

from .xprompt_browser_helpers import BrowserItem, append_input_args


def browser_hint_text(*, loadable: bool) -> str:
    """Return the hint line, showing ``^i: load`` only for loadable rows.

    ``^i`` inline-loads the highlighted xprompt into the prompt bar and is
    inactive for YAML-backed rows (workflows and config-backed entries), so the
    hint surfaces it only when the current selection is eligible.
    """
    load_hint = "^i: load  " if loadable else ""
    return (
        f"^n/^p: navigate  enter: edit here  E: $EDITOR  {load_hint}^o: add new  "
        "^d/^u: scroll  [ / ]: switch tab  Esc: close"
    )


def create_browser_options(
    grouped: list[tuple[str, list[BrowserItem]]],
) -> list[Option]:
    """Create OptionList items with group headers as disabled options."""
    options: list[Option] = []
    for category, items in grouped:
        header_text = Text(f"── {category} ──", style="bold dim")
        options.append(Option(header_text, id=f"__header__{category}", disabled=True))
        for item in items:
            options.append(Option(create_item_label(item), id=f"item__{item.name}"))
    return options


def create_item_label(item: BrowserItem) -> Text:
    """Create styled label for an xprompt item."""
    text = Text()
    prefix = workflow_reference_prefix(item.workflow)
    if item.kind == "standalone_workflow":
        text.append("  ▶ ", style="bold #FFD700")
        text.append(prefix, style="bold #87D7FF")
    elif item.kind == "embeddable_workflow":
        text.append("  ⚙ ", style="bold #FFD700")
        text.append(prefix, style="bold #87D7FF")
    else:
        text.append(f"  {prefix}", style="bold #87D7FF")
    text.append(item.name)
    append_input_args(text, item.workflow.inputs)
    return text


__all__ = ["browser_hint_text", "create_browser_options", "create_item_label"]
