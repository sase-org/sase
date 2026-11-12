"""Lexical helpers for detecting macro references."""

from __future__ import annotations

import re

from sase.macro._directive_types import KEY_MARKER_PATTERN
from ._parsing import iter_macro_references
from .models import Macro
from .project_identity import canonical_macro_project, known_project_namespaces

# Pattern to match macro references: #name, #name(, #name:arg, or #name+
# Must be at start of string, after whitespace, or after certain punctuation
# Note: No space allowed after # (to avoid matching markdown headings)
# Supports:
#   - #name - simple macro (no args)
#   - #name( - parenthesis syntax start (matching ) found programmatically)
#   - #name:arg - colon syntax for args (word-like chars, comma-separated for multiple)
#   - #name:`arg` - colon syntax with backtick-delimited arg (any content)
#   - #name:$(cmd) - colon syntax with command substitution
#   - #name+ - plus syntax, equivalent to #name:true
# The colon arg also admits a keyed `{@<id>}` agent-name marker as an
# indivisible unit, so #fork:research.{@1!}.final survives lexing.
MACRO_PATTERN = (
    r"(?:^|(?<=\s)|(?<=[(\[{\"']))"  # Must be at start, after whitespace, or after ([{"'
    r"#([a-zA-Z_][a-zA-Z0-9_]*(?:/[a-zA-Z_][a-zA-Z0-9_]*)*)"  # Group 1: macro name with optional namespace
    r"(?:(\()|:(`[^`]*`|\$\([^)]*\)|"  # Group 2: open paren OR Group 3: colon arg (backtick, $(cmd), or word)
    rf"(?:{KEY_MARKER_PATTERN}|[a-zA-Z0-9_.~,+/@-])*"  # arg body
    rf"(?:{KEY_MARKER_PATTERN}|[a-zA-Z0-9_~,+/@-])"  # arg must not end in .
    r")|(\+))?"  # Group 4: plus
)

_COMMON_VCS_MACRO_NAMES = frozenset({"gh", "git", "p4"})

# Launch analysis must discover metadata contributed by ordinary macros without
# executing workflows whose expansion reads mutable agent state.  Callers retain
# these references until the runner has admitted their dependency barrier.
LAUNCH_DEFERRED_MACRO_NAMES: frozenset[str] = frozenset({"fork"})


def _candidate_name(match: re.Match[str]) -> str:
    """Return the macro name represented by a regex match."""
    return match.group(1).replace("__", "/")


def _is_obvious_vcs_only_reference(match: re.Match[str], prompt: str) -> bool:
    """Return True for common leading VCS tags that are not macro refs."""
    prefix = prompt[: match.start()].strip()
    if prefix and not all(part.startswith("%") for part in prefix.split()):
        return False

    raw_name = match.group(1)
    if raw_name in _COMMON_VCS_MACRO_NAMES:
        return (
            match.group(2) is not None
            or match.group(3) is not None
            or match.group(4) is not None
        )
    return any(raw_name.startswith(f"{name}_") for name in _COMMON_VCS_MACRO_NAMES)


def prompt_may_reference_macro(
    prompt: str, extra_macros: dict[str, Macro] | None = None
) -> bool:
    """Cheaply detect whether *prompt* might contain a macro reference.

    This is intentionally lexical and conservative.  It avoids loading the
    full macro catalog for prompts that clearly cannot expand, while still
    returning True for ambiguous ``#name`` forms so the normal processor can
    decide using the real catalog.
    """
    if "#" not in prompt:
        return False

    extra_names = set(extra_macros or {})
    for match in re.finditer(MACRO_PATTERN, prompt, re.MULTILINE):
        name = _candidate_name(match)
        if name in extra_names:
            return True
        if _is_obvious_vcs_only_reference(match, prompt):
            continue
        return True
    return False


def resolve_macro_aliases(prompt: str) -> str:
    """Resolve project aliases and macro aliases via raw text substitution.

    Aliases are defined in the ``macro_aliases`` config field and are
    substituted *before* any other macro processing.  This allows aliases
    like ``#c`` → ``#commit`` where the expanded syntax must be present
    in the raw text for later resolution logic.
    """
    if "#" not in prompt:
        return prompt

    from sase.project_aliases import canonicalize_project_aliases_in_prompt

    prompt = canonicalize_project_aliases_in_prompt(prompt)

    from sase.config import load_merged_config

    aliases: dict[str, str] = load_merged_config().get("macro_aliases", {})
    if not aliases:
        return prompt

    for alias_name, target in aliases.items():
        pattern = (
            r"(?:^|(?<=\s)|(?<=[(\[{\"']))"
            r"#" + re.escape(alias_name) + r"(?![a-zA-Z0-9_/])"
        )
        prompt = re.sub(pattern, f"#{target}", prompt, flags=re.MULTILINE)

    return prompt


def registered_project_namespace_from_prompt(prompt: str) -> str | None:
    """Return the first registered namespace referenced by *prompt*."""
    known_projects = known_project_namespaces()
    if not known_projects:
        return None

    for reference in iter_macro_references(prompt):
        namespace, separator, _name = reference.name.partition("/")
        if not separator:
            continue
        canonical = canonical_macro_project(namespace)
        if canonical in known_projects:
            return canonical
    return None
