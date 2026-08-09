"""String, property, and recursive expression matchers for query evaluation."""

import re

from ..patch import Patch, has_any_status_suffix
from .searchable import RUNNING_AGENT_MARKER, RUNNING_PROCESS_MARKER
from .types import AndExpr, NotExpr, OrExpr, PropertyMatch, QueryExpr, StringMatch

_WORKSPACE_SUFFIX_RE = re.compile(r" \([a-zA-Z0-9_-]+_\d+\)$")
_LEGACY_READY_TO_MAIL_RE = re.compile(r" - \(!\: READY TO MAIL\)$")


def _match_string(text: str, match: StringMatch) -> bool:
    """Check if text contains the string match.

    Args:
        text: The text to search in.
        match: The StringMatch to check.

    Returns:
        True if the text contains the match value.
    """
    if match.case_sensitive:
        return match.value in text
    return match.value.lower() in text.lower()


def get_base_status(status: str) -> str:
    """Get base status without workspace suffix or legacy READY TO MAIL suffix.

    Args:
        status: The full status string (e.g., "Ready (fig_1)").

    Returns:
        The base status value (e.g., "Ready").
    """
    status = _WORKSPACE_SUFFIX_RE.sub("", status)
    status = _LEGACY_READY_TO_MAIL_RE.sub("", status)
    return status.strip()


def _match_status(prop: PropertyMatch, patch: Patch) -> bool:
    """Match against Patch STATUS field.

    Args:
        prop: The PropertyMatch with key="status".
        patch: The Patch to check.

    Returns:
        True if the base status matches (case-insensitive).
    """
    base_status = get_base_status(patch.status)
    return base_status.lower() == prop.value.lower()


def _match_project(prop: PropertyMatch, patch: Patch) -> bool:
    """Match against the effective Patch project query name.

    Args:
        prop: The PropertyMatch with key="project".
        patch: The Patch to check.

    Returns:
        True if the configured display name, or directory-key fallback,
        matches case-insensitively.
    """
    return patch.project_query_name.lower() == prop.value.lower()


def _match_name(prop: PropertyMatch, patch: Patch) -> bool:
    """Match against Patch NAME field.

    Args:
        prop: The PropertyMatch with key="name".
        patch: The Patch to check.

    Returns:
        True if the name matches exactly (case-insensitive).
    """
    return patch.name.lower() == prop.value.lower()


def _match_sibling(prop: PropertyMatch, patch: Patch) -> bool:
    """Match if Patch is in the same sibling family as the given name.

    A Patch matches if its base name (with __<N> suffix stripped) equals
    the search value's base name (also with any __<N> suffix stripped).

    This matches all Patches that share the same "family" - the exact name
    plus all its __1, __2, etc. variants.

    Args:
        prop: The PropertyMatch with key="sibling".
        patch: The Patch to check.

    Returns:
        True if the base names match (case-insensitive).
    """
    from sase.core.patch import strip_reverted_suffix

    # Get the base name of the search value (strip __<N> suffix)
    search_base = strip_reverted_suffix(prop.value).lower()

    # Get the base name of the patch's name
    cs_base = strip_reverted_suffix(patch.name).lower()

    # Match if base names are equal
    return cs_base == search_base


def _match_ancestor(
    prop: PropertyMatch,
    patch: Patch,
    all_patches: list[Patch] | None,
) -> bool:
    """Match if Patch name or parent chain includes the ancestor value.

    Args:
        prop: The PropertyMatch with key="ancestor".
        patch: The Patch to check.
        all_patches: List of all Patches for parent chain lookup.

    Returns:
        True if the Patch's name matches the ancestor value, or if any
        parent in the chain (recursively) matches. Returns False if
        all_patches is None.
    """
    if all_patches is None:
        return False

    ancestor_value = prop.value.lower()

    # Build name -> Patch map for efficient lookup
    name_map: dict[str, Patch] = {}
    for cs in all_patches:
        name_map[cs.name.lower()] = cs

    # Check if this Patch or any ancestor matches
    visited: set[str] = set()

    def _has_ancestor(cs: Patch) -> bool:
        """Recursively check if Patch has the ancestor."""
        cs_name_lower = cs.name.lower()

        # Cycle detection
        if cs_name_lower in visited:
            return False
        visited.add(cs_name_lower)

        # Check if this Patch's name matches
        if cs_name_lower == ancestor_value:
            return True

        # Check if parent matches
        if cs.parent:
            parent_lower = cs.parent.lower()
            if parent_lower == ancestor_value:
                return True
            # Recursively check parent's ancestors
            if parent_lower in name_map:
                return _has_ancestor(name_map[parent_lower])

        return False

    return _has_ancestor(patch)


def match_property(
    prop: PropertyMatch,
    patch: Patch,
    all_patches: list[Patch] | None,
) -> bool:
    """Match a property filter against a Patch.

    Args:
        prop: The PropertyMatch to evaluate.
        patch: The Patch to check.
        all_patches: List of all Patches (required for ancestor matching).

    Returns:
        True if the property matches.
    """
    if prop.key == "status":
        return _match_status(prop, patch)
    elif prop.key == "project":
        return _match_project(prop, patch)
    elif prop.key == "ancestor":
        return _match_ancestor(prop, patch, all_patches)
    elif prop.key == "name":
        return _match_name(prop, patch)
    elif prop.key == "sibling":
        return _match_sibling(prop, patch)
    else:
        # Unknown property key - should not happen with proper tokenization
        return False


def evaluate(
    expr: QueryExpr,
    text: str,
    patch: Patch,
    all_patches: list[Patch] | None = None,
) -> bool:
    """Recursively evaluate an expression against text.

    Args:
        expr: The query expression to evaluate.
        text: The text to match against.
        patch: The Patch being evaluated (for special handling).
        all_patches: List of all Patches (required for ancestor matching).

    Returns:
        True if the expression matches the text.

    Raises:
        TypeError: If the expression type is unknown.
    """
    if isinstance(expr, StringMatch):
        # Special handling for error suffix shorthand (!!!)
        if expr.is_error_suffix:
            return has_any_status_suffix(patch)
        # Special handling for running agent shorthand (@@@)
        # Simply check for "- (@" marker in the searchable text
        if expr.is_running_agent:
            return RUNNING_AGENT_MARKER in text
        # Special handling for running process shorthand ($$$)
        # Simply check for "- ($: " marker in the searchable text
        if expr.is_running_process:
            return RUNNING_PROCESS_MARKER in text
        return _match_string(text, expr)
    elif isinstance(expr, PropertyMatch):
        return match_property(expr, patch, all_patches)
    elif isinstance(expr, NotExpr):
        return not evaluate(expr.operand, text, patch, all_patches)
    elif isinstance(expr, AndExpr):
        return all(evaluate(op, text, patch, all_patches) for op in expr.operands)
    elif isinstance(expr, OrExpr):
        return any(evaluate(op, text, patch, all_patches) for op in expr.operands)
    else:
        raise TypeError(f"Unknown expression type: {type(expr)}")
