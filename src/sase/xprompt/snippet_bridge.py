"""Bridge between xprompt definitions and ACE snippet templates."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
import re

from sase.xprompt._parsing_args import (
    find_matching_bracket_for_args,
    parse_workflow_reference,
)
from sase.xprompt.models import UNSET, XPrompt
from sase.xprompt.processor import process_xprompt_references_with_catalog

_JINJA2_CONTROL = re.compile(r"\{%.*?%\}", re.DOTALL)
_JINJA2_COMMENT = re.compile(r"\{#.*?#\}", re.DOTALL)
_JINJA2_EXPR = re.compile(r"\{\{(.*?)\}\}")
_LEGACY_PLACEHOLDER = re.compile(r"\{(\d+)(?::([^}]*))?\}")
_VALID_TRIGGER = re.compile(r"^[a-zA-Z0-9_]+$")
_SNIPPET_REF_PREFIX_CHARS = set("([{\"'")


@dataclass(frozen=True)
class XPromptSnippetEntry:
    """Snippet template derived from an xprompt definition."""

    trigger: str
    template: str
    xprompt_name: str
    description: str | None = None
    source_path_display: str | None = None


def is_valid_snippet_trigger(trigger: str) -> bool:
    """Return True when ACE can expand ``trigger`` as a bare word."""
    return bool(_VALID_TRIGGER.fullmatch(trigger))


def resolve_snippet_references(catalog: Mapping[str, str]) -> dict[str, str]:
    """Resolve ``#[snippet]`` references in a merged snippet catalog.

    References target catalog triggers, so this must run after xprompt-derived
    snippets and user ``ace.snippets`` have been merged.
    """
    resolver = _SnippetReferenceResolver(catalog)
    return {trigger: resolver.resolve(trigger) for trigger in catalog}


class _SnippetReferenceResolver:
    def __init__(self, catalog: Mapping[str, str]) -> None:
        self._catalog = catalog
        self._memo: dict[str, str] = {}

    def resolve(self, trigger: str) -> str:
        if trigger in self._memo:
            return self._memo[trigger]
        template = self._catalog[trigger]
        resolved = self._resolve_template(template, visiting={trigger})
        self._memo[trigger] = resolved
        return resolved

    def _resolve_template(self, template: str, *, visiting: set[str]) -> str:
        segments: list[tuple[int, str]] = []
        next_source_id = 1
        used_reference = False
        cursor = 0
        literal_start = 0

        while cursor < len(template):
            if not _starts_snippet_reference(template, cursor):
                cursor += 1
                continue

            close = find_matching_bracket_for_args(template, cursor + 1)
            if close is None:
                cursor += 1
                continue

            body = template[cursor + 2 : close]
            name, positional_args, _named_args = parse_workflow_reference(body)
            if name not in self._catalog or name in visiting:
                cursor = close + 1
                continue

            if literal_start < cursor:
                segments.append((0, template[literal_start:cursor]))

            target = self._resolve_reference(
                name,
                positional_args=positional_args,
                visiting=visiting,
            )
            segments.append((next_source_id, target))
            next_source_id += 1
            used_reference = True
            cursor = close + 1
            literal_start = cursor

        if not used_reference:
            return template

        if literal_start < len(template):
            segments.append((0, template[literal_start:]))

        return _renumber_snippet_segments(segments)

    def _resolve_reference(
        self,
        trigger: str,
        *,
        positional_args: list[str],
        visiting: set[str],
    ) -> str:
        if trigger in self._memo:
            template = self._memo[trigger]
        else:
            visiting.add(trigger)
            try:
                template = self._resolve_template(
                    self._catalog[trigger],
                    visiting=visiting,
                )
            finally:
                visiting.remove(trigger)
            self._memo[trigger] = template

        fragment = _remove_zero_tabstops(template)
        return _apply_positional_args(fragment, positional_args)


def _starts_snippet_reference(text: str, index: int) -> bool:
    if text[index : index + 2] != "#[":
        return False
    if index == 0:
        return True
    previous = text[index - 1]
    return previous.isspace() or previous in _SNIPPET_REF_PREFIX_CHARS


def _apply_positional_args(fragment: str, positional_args: list[str]) -> str:
    if not positional_args:
        return fragment

    replacements = {
        index: _escape_snippet_arg(value)
        for index, value in enumerate(positional_args, start=1)
    }
    rendered: list[str] = []
    cursor = 0
    for start, end, number in _iter_unescaped_tabstops(fragment):
        rendered.append(fragment[cursor:start])
        rendered.append(replacements.get(number, fragment[start:end]))
        cursor = end
    rendered.append(fragment[cursor:])
    return "".join(rendered)


def _escape_snippet_arg(value: str) -> str:
    return value.replace("$", r"\$")


def _remove_zero_tabstops(template: str) -> str:
    rendered: list[str] = []
    cursor = 0
    for start, end, number in _iter_unescaped_tabstops(template):
        rendered.append(template[cursor:start])
        if number != 0:
            rendered.append(template[start:end])
        cursor = end
    rendered.append(template[cursor:])
    return "".join(rendered)


def _renumber_snippet_segments(segments: list[tuple[int, str]]) -> str:
    assignments: dict[tuple[int, int], int] = {}
    next_tabstop = 1
    rendered: list[str] = []

    for source_id, text in segments:
        cursor = 0
        for start, end, number in _iter_unescaped_tabstops(text):
            rendered.append(text[cursor:start])
            if number != 0:
                key = (source_id, number)
                assigned = assignments.get(key)
                if assigned is None:
                    assigned = next_tabstop
                    assignments[key] = assigned
                    next_tabstop += 1
                rendered.append(f"${assigned}")
            cursor = end
        rendered.append(text[cursor:])

    return "".join(rendered) + "$0"


def _iter_unescaped_tabstops(text: str) -> list[tuple[int, int, int]]:
    tabstops: list[tuple[int, int, int]] = []
    cursor = 0
    while cursor < len(text):
        if text[cursor] != "$" or _is_escaped(text, cursor):
            cursor += 1
            continue
        digit_start = cursor + 1
        digit_end = digit_start
        while digit_end < len(text) and text[digit_end].isdigit():
            digit_end += 1
        if digit_end == digit_start:
            cursor += 1
            continue
        tabstops.append((cursor, digit_end, int(text[digit_start:digit_end])))
        cursor = digit_end
    return tabstops


def _is_escaped(text: str, index: int) -> bool:
    backslashes = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 1


def _xprompt_to_snippet_template(xp: XPrompt) -> str | None:
    """Convert an xprompt's content + inputs into a snippet template string.

    Returns None if the xprompt can't be converted (complex Jinja2).
    """
    content = xp.content

    # Bail out on complex Jinja2
    if _JINJA2_CONTROL.search(content) or _JINJA2_COMMENT.search(content):
        return None

    input_names = {inp.name for inp in xp.inputs}

    # Check all {{ expr }} — bail if any expr is not a simple input name
    for match in _JINJA2_EXPR.finditer(content):
        expr = match.group(1).strip()
        if expr and expr not in input_names:
            return None

    # Assign tabstop numbers to required inputs (in definition order)
    tabstop = 1
    tabstop_map: dict[str, str] = {}
    for inp in xp.inputs:
        if inp.default is UNSET:
            tabstop_map[inp.name] = f"${tabstop}"
            tabstop += 1
        else:
            # Pre-fill with default value
            tabstop_map[inp.name] = "" if inp.default is None else str(inp.default)

    # Replace {{ name }} with tabstop or default
    def _replace_jinja_expr(m: re.Match[str]) -> str:
        expr = m.group(1).strip()
        return tabstop_map.get(expr, m.group(0))

    result = _JINJA2_EXPR.sub(_replace_jinja_expr, content)

    # Handle legacy {N} and {N:default} placeholders
    def _replace_legacy(m: re.Match[str]) -> str:
        num = m.group(1)
        default = m.group(2)
        if default is not None:
            return default
        return f"${num}"

    result = _LEGACY_PLACEHOLDER.sub(_replace_legacy, result)

    return result + "$0"


def build_xprompt_snippet_entries_from_catalog(
    xprompts: Mapping[str, XPrompt],
) -> list[XPromptSnippetEntry]:
    """Build xprompt snippets from an already-loaded xprompt catalog.

    Args:
        xprompts: XPrompt catalog in loader precedence order.

    Returns:
        Entries in loader priority order. The first xprompt wins on trigger
        collision, matching :func:`_get_xprompt_snippets`.
    """
    entries: list[XPromptSnippetEntry] = []
    seen_triggers: set[str] = set()

    for xp in xprompts.values():
        if xp.snippet is None:
            continue

        # Resolve trigger
        if isinstance(xp.snippet, str):
            trigger = xp.snippet
        else:
            # snippet: true — use base name (part after last /)
            parts = xp.name.rsplit("/", 1)
            trigger = parts[-1]

        if not is_valid_snippet_trigger(trigger):
            continue

        composed_content = process_xprompt_references_with_catalog(
            xp.content,
            dict(xprompts),
        )
        composed_xp = replace(xp, content=composed_content)

        template = _xprompt_to_snippet_template(composed_xp)
        if template is None:
            continue

        # First xprompt wins on trigger collision (higher-priority source loaded first)
        if trigger in seen_triggers:
            continue
        seen_triggers.add(trigger)
        entries.append(
            XPromptSnippetEntry(
                trigger=trigger,
                template=template,
                xprompt_name=xp.name,
                description=xp.description,
                source_path_display=xp.source_path,
            )
        )

    return entries


def get_xprompt_snippet_entries(
    project: str | None = None,
) -> list[XPromptSnippetEntry]:
    """Load xprompt snippets with metadata preserved for editor integrations.

    Args:
        project: Optional project name for xprompt loading.

    Returns:
        Entries in loader priority order. The first xprompt wins on trigger
        collision, matching :func:`_get_xprompt_snippets`.
    """
    from sase.xprompt.loader import get_all_xprompts

    return build_xprompt_snippet_entries_from_catalog(get_all_xprompts(project=project))


def _get_xprompt_snippets(project: str | None = None) -> dict[str, str]:
    """Load all xprompts with ``snippet`` set and return a trigger-to-template dict.

    Args:
        project: Optional project name for xprompt loading.

    Returns:
        Dict mapping trigger word to snippet template string.
    """
    snippets: dict[str, str] = {}
    for entry in get_xprompt_snippet_entries(project=project):
        snippets[entry.trigger] = entry.template

    return snippets
