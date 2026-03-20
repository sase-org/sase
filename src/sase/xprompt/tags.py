"""XPrompt tag system for semantic role-based lookup."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.xprompt.workflow_models import Workflow


class XPromptTag(Enum):
    """Semantic tags for xprompts and workflows."""

    VCS = "vcs"
    CRS = "crs"
    FIX_HOOK = "fix_hook"
    ROLLOVER = "rollover"


def parse_tags(raw: str | list[str] | None) -> set[XPromptTag]:
    """Parse raw tag data into a set of XPromptTag values.

    Accepts a comma-separated string, a list of strings, or None.

    Args:
        raw: Tag data from YAML — comma-separated string, list, or None.

    Returns:
        Set of parsed XPromptTag values.

    Raises:
        ValueError: If an unknown tag name is encountered.
    """
    if raw is None:
        return set()

    if isinstance(raw, str):
        names = [t.strip() for t in raw.split(",") if t.strip()]
    elif isinstance(raw, list):
        names = [str(t).strip() for t in raw if str(t).strip()]
    else:
        return set()

    valid = {t.value for t in XPromptTag}
    tags: set[XPromptTag] = set()
    for name in names:
        if name not in valid:
            raise ValueError(
                f"Unknown xprompt tag '{name}'. Valid tags: {sorted(valid)}"
            )
        tags.add(XPromptTag(name))
    return tags


def get_by_tag(tag: XPromptTag, project: str | None = None) -> Workflow | None:
    """Find the highest-priority workflow with the given tag.

    Uses the standard loader precedence (local > user > plugin > builtin).
    For singleton tags (crs, fix_hook), returns the first match.

    Args:
        tag: The tag to search for.
        project: Optional project name for scoped lookups.

    Returns:
        The highest-priority Workflow with the tag, or None.
    """
    from sase.xprompt.loader import get_all_prompts

    all_prompts = get_all_prompts(project=project)
    for workflow in all_prompts.values():
        if workflow.has_tag(tag):
            return workflow
    return None
