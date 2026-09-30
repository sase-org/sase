"""Jinja2 completion candidates for the prompt input bar.

Candidates come from the shared Rust engine (``sase-core``
``editor::jinja``) through :mod:`sase.xprompt.jinja_assist`, so the menu
offers exactly what the unknown-variable lint accepts. The engine ranks,
fuzzy-matches, and documents every item; this module only rehydrates the
items as :class:`CompletionCandidate` rows carrying display metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.xprompt import jinja_assist


@dataclass(frozen=True, slots=True)
class JinjaCompletionMetadata:
    """Display metadata for a Jinja2 completion candidate."""

    kind: str
    source: str = "jinja"
    type_label: str | None = None
    signature: str | None = None
    required: bool = False
    default_display: str | None = None
    choices: tuple[str, ...] = ()
    availability: str = "available"
    hint: str | None = None
    legacy_for: str | None = None
    closes: str | None = None
    shadows: str | None = None
    match_runs: tuple[tuple[int, int], ...] = ()
    summary: str | None = None
    slot: str = "variable"
    namespace: str | None = None
    scope_label: str | None = None


@dataclass(frozen=True, slots=True)
class JinjaCompletionResult:
    """Completion context plus candidates for a Jinja2 tag."""

    prefix: str
    replacement_start: int
    replacement_end: int
    candidates: list[CompletionCandidate]
    shared_extension: str
    slot: str = "variable"
    namespace: str | None = None
    scope_label: str | None = None


def jinja_scope_for_editor(editor: Any) -> jinja_assist.JinjaScope:
    """Return the engine scope for a prompt text area's owner.

    The scope is computed on the UI thread from the owning prompt bar's
    frontmatter state; workers and pure paths that only have text fall
    back to prompt scope without frontmatter.
    """
    bar = None
    finder = getattr(editor, "_find_prompt_bar", None)
    if callable(finder):
        try:
            bar = finder()
        except Exception:
            bar = None
    scope_getter = getattr(bar, "jinja_scope_for_text_area", None)
    if callable(scope_getter):
        try:
            return scope_getter(editor)
        except Exception:
            pass
    return jinja_assist.JinjaScope(kind="prompt", frontmatter=None)


def jinja_scope_label_for_editor(editor: Any) -> str | None:
    """Return the scope label (``#name``) for a prompt text area, if any."""
    bar = None
    finder = getattr(editor, "_find_prompt_bar", None)
    if callable(finder):
        try:
            bar = finder()
        except Exception:
            bar = None
    label_getter = getattr(bar, "jinja_scope_label_for_text_area", None)
    if callable(label_getter):
        try:
            label = label_getter(editor)
        except Exception:
            return None
        return str(label) if label else None
    return None


def _completion_items(
    completion: jinja_assist.JinjaCompletion,
) -> tuple[jinja_assist.JinjaCompletionItem, ...]:
    """Return the engine's ranked items for *completion*."""
    return completion.items


def _availability_of(
    item: jinja_assist.JinjaCompletionItem,
) -> jinja_assist.JinjaAvailability:
    """Return the availability record for a completion *item*."""
    return item.availability


def build_jinja_completion_result(
    text: str,
    cursor_offset: int,
    scope: jinja_assist.JinjaScope | None = None,
    *,
    scope_label: str | None = None,
) -> JinjaCompletionResult | None:
    """Return engine-backed Jinja2 completions at *cursor_offset*.

    Returns ``None`` when the cursor is outside any Jinja tag. An in-tag
    position with no candidates (for example a ``none`` slot) still
    returns a result with empty items so the Jinja branch claims the
    cursor ahead of every other completion surface.
    """
    active_scope = scope or jinja_assist.JinjaScope(kind="prompt", frontmatter=None)
    completion: jinja_assist.JinjaCompletion | None = jinja_assist.jinja_completion(
        text, cursor_offset, active_scope
    )
    if completion is None:
        return None
    items = _completion_items(completion)
    candidates = []
    for item in items:
        availability = _availability_of(item)
        candidates.append(
            CompletionCandidate(
                display=item.name,
                insertion=item.insertion,
                is_dir=False,
                name=item.name,
                metadata=JinjaCompletionMetadata(
                    kind=item.kind,
                    source=item.source,
                    type_label=item.type_label,
                    signature=item.signature,
                    required=item.required,
                    default_display=item.default_display,
                    choices=item.choices,
                    availability=availability.state,
                    hint=availability.hint,
                    legacy_for=item.legacy_for,
                    closes=item.closes,
                    shadows=item.shadows,
                    match_runs=item.match_runs,
                    summary=item.summary,
                    slot=completion.slot,
                    namespace=completion.namespace,
                    scope_label=scope_label,
                ),
            )
        )
    return JinjaCompletionResult(
        prefix=completion.prefix,
        replacement_start=completion.replacement_start,
        replacement_end=completion.replacement_end,
        candidates=candidates,
        shared_extension=completion.shared_extension,
        slot=completion.slot,
        namespace=completion.namespace,
        scope_label=scope_label,
    )
