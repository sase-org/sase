"""Catalog loading and grouping helpers for the XPrompt browser pane."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from sase.xprompt.reference_display import (
    workflow_kind_value,
    workflow_reference_insertion,
)
from sase.xprompt.workflow_models import Workflow

from .xprompt_browser_helpers import BrowserItem


class _PromptLoader(Protocol):
    """Callable shape for loading global xprompts."""

    def __call__(self, *, project: str | None = None) -> dict[str, Workflow]: ...


SourceClassifier = Callable[[str | None], tuple[str, str, bool]]


def load_browser_items(
    project: str | None,
    *,
    prompt_loader: _PromptLoader,
    source_classifier: SourceClassifier,
) -> list[BrowserItem]:
    """Load xprompts and convert them into browser rows."""
    prompts = prompt_loader(project=project)

    # Also load project-local xprompts from ALL known projects' sase.yml files.
    # These are not loaded by get_all_prompts() because the TUI disables
    # _include_local_config.
    from sase.xprompt.loader import get_all_project_local_prompts

    project_local = get_all_project_local_prompts()
    prompts = {**project_local, **prompts}

    items: list[BrowserItem] = []
    for name, workflow in prompts.items():
        source_path = workflow.source_path
        category, display_path, is_editable = source_classifier(source_path)
        item_type = "xprompt" if workflow.is_simple_xprompt() else "workflow"
        kind = workflow_kind_value(workflow)
        items.append(
            BrowserItem(
                name=name,
                workflow=workflow,
                source_category=category,
                source_path=source_path,
                display_path=display_path,
                is_editable=is_editable,
                item_type=item_type,
                kind=kind,
                insertion=workflow_reference_insertion(name, workflow),
            )
        )

    return items


def group_browser_items(
    items: list[BrowserItem], filter_text: str = ""
) -> list[tuple[str, list[BrowserItem]]]:
    """Group browser rows by source category, optionally filtered."""
    filter_lower = filter_text.lower()
    filtered = (
        [item for item in items if item_matches_filter(item, filter_lower)]
        if filter_lower
        else list(items)
    )

    groups: dict[str, list[BrowserItem]] = {}
    for item in filtered:
        groups.setdefault(item.source_category, []).append(item)

    for items_list in groups.values():
        items_list.sort(key=lambda x: x.name)

    known_order = [
        "Project sase/xprompts/",
        "Project xprompts/ (legacy)",
        "Home ~/sase/xprompts/",
        "Home xprompts/ (legacy)",
    ]

    ordered: list[tuple[str, list[BrowserItem]]] = []
    seen: set[str] = set()

    for category in known_order:
        if category in groups:
            ordered.append((category, groups[category]))
            seen.add(category)

    for category in sorted(groups.keys()):
        if (
            category.startswith(("Project (", "Project home ("))
            and category not in seen
        ):
            ordered.append((category, groups[category]))
            seen.add(category)

    if "User sase.yml" in groups and "User sase.yml" not in seen:
        ordered.append(("User sase.yml", groups["User sase.yml"]))
        seen.add("User sase.yml")

    for category in sorted(groups.keys()):
        if category.startswith("Plugin (") and category not in seen:
            ordered.append((category, groups[category]))
            seen.add(category)

    if "Built-in" in groups and "Built-in" not in seen:
        ordered.append(("Built-in", groups["Built-in"]))
        seen.add("Built-in")

    for category in sorted(groups.keys()):
        if category not in seen:
            ordered.append((category, groups[category]))

    return ordered


def item_matches_filter(item: BrowserItem, filter_lower: str) -> bool:
    """Return True when a browser row matches the lowercase filter string."""
    parts = [item.name, item.workflow.description or ""]
    parts.extend(
        inp.description or "" for inp in item.workflow.inputs if not inp.is_step_input
    )
    return filter_lower in "\n".join(part for part in parts if part).casefold()


def flatten_grouped_items(
    grouped: list[tuple[str, list[BrowserItem]]],
) -> list[BrowserItem]:
    """Flatten grouped browser rows into display order."""
    result: list[BrowserItem] = []
    for _, items in grouped:
        result.extend(items)
    return result


__all__ = [
    "SourceClassifier",
    "flatten_grouped_items",
    "group_browser_items",
    "item_matches_filter",
    "load_browser_items",
]
