"""Bridge between xprompt definitions and ACE snippet templates."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
import re

from sase.xprompt.models import UNSET, XPrompt
from sase.xprompt.processor import process_xprompt_references_with_catalog

_JINJA2_CONTROL = re.compile(r"\{%.*?%\}", re.DOTALL)
_JINJA2_COMMENT = re.compile(r"\{#.*?#\}", re.DOTALL)
_JINJA2_EXPR = re.compile(r"\{\{(.*?)\}\}")
_LEGACY_PLACEHOLDER = re.compile(r"\{(\d+)(?::([^}]*))?\}")
_VALID_TRIGGER = re.compile(r"^[a-zA-Z0-9_]+$")


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
    *,
    include_shadowed: bool = False,
) -> list[XPromptSnippetEntry]:
    """Build xprompt snippets from an already-loaded xprompt catalog.

    Args:
        xprompts: XPrompt catalog in loader precedence order.
        include_shadowed: When true, keep later xprompts that reuse a trigger
            already claimed by a higher-priority source.

    Returns:
        Entries in loader priority order. The first xprompt wins on trigger
        collision, matching :func:`_get_xprompt_snippets`, unless
        *include_shadowed* is true.
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
        if trigger in seen_triggers and not include_shadowed:
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
