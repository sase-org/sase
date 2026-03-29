"""Bridge between xprompt definitions and ACE snippet templates."""

import re

from sase.xprompt.models import UNSET, XPrompt

_JINJA2_CONTROL = re.compile(r"\{%.*?%\}", re.DOTALL)
_JINJA2_COMMENT = re.compile(r"\{#.*?#\}", re.DOTALL)
_JINJA2_EXPR = re.compile(r"\{\{(.*?)\}\}")
_LEGACY_PLACEHOLDER = re.compile(r"\{(\d+)(?::([^}]*))?\}")
_VALID_TRIGGER = re.compile(r"^[a-zA-Z0-9_]+$")


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


def get_xprompt_snippets(project: str | None = None) -> dict[str, str]:
    """Load all xprompts with ``snippet`` set and return a trigger-to-template dict.

    Args:
        project: Optional project name for xprompt loading.

    Returns:
        Dict mapping trigger word to snippet template string.
    """
    from sase.xprompt.loader import get_all_xprompts

    xprompts = get_all_xprompts(project=project)
    snippets: dict[str, str] = {}

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

        if not _VALID_TRIGGER.match(trigger):
            continue

        template = _xprompt_to_snippet_template(xp)
        if template is None:
            continue

        # First xprompt wins on trigger collision (higher-priority source loaded first)
        if trigger not in snippets:
            snippets[trigger] = template

    return snippets
