"""XPrompt tag system for semantic role tagging."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.xprompt.workflow_models import Workflow


class XPromptTag(Enum):
    """Semantic role tags for xprompts and workflows."""

    vcs = "vcs"
    crs = "crs"
    fix_hook = "fix_hook"
    rollover = "rollover"
    mentor = "mentor"
    commit = "commit"
    make_mentor_changes = "make_mentor_changes"


def parse_tags(raw: str | list[str] | None) -> frozenset[XPromptTag]:
    """Parse tags from YAML data into a frozenset of XPromptTag.

    Accepts comma-separated string (``tags: vcs, rollover``),
    list (``tags: [vcs, rollover]``), or None.

    Raises:
        ValueError: If an unknown tag name is encountered.
    """
    if raw is None:
        return frozenset()

    if isinstance(raw, str):
        names = [s.strip() for s in raw.split(",") if s.strip()]
    else:
        names = [str(s).strip() for s in raw if str(s).strip()]

    valid = {t.value for t in XPromptTag}
    tags: list[XPromptTag] = []
    for name in names:
        if name not in valid:
            raise ValueError(
                f"Unknown xprompt tag {name!r}. Valid tags: {sorted(valid)}"
            )
        tags.append(XPromptTag(name))
    return frozenset(tags)


def get_by_tag(tag: XPromptTag, project: str | None = None) -> Workflow | None:
    """Find the highest-priority xprompt/workflow with the given tag.

    Uses ``get_all_prompts()`` so the loader's existing precedence
    (local > user > plugin > builtin) naturally handles override order.

    Returns the first matching Workflow, or None.
    """
    from sase.xprompt.loader import get_all_prompts

    for wf in get_all_prompts(project=project).values():
        if tag in wf.tags:
            return wf
    return None


def get_by_tag_strict(tag: XPromptTag, project: str | None = None) -> Workflow | None:
    """Find the xprompt/workflow with the given tag, enforcing uniqueness.

    Like :func:`get_by_tag`, but raises :class:`ValueError` if multiple
    xprompts share the same tag. When only one match exists, returns it.

    Returns:
        The matching Workflow, or ``None`` if no match.

    Raises:
        ValueError: If more than one xprompt/workflow has the tag.
    """
    from sase.xprompt.loader import get_all_prompts

    matches: list[Workflow] = []
    for wf in get_all_prompts(project=project).values():
        if tag in wf.tags:
            matches.append(wf)

    if len(matches) > 1:
        names = [m.name for m in matches]
        raise ValueError(
            f"Multiple xprompts found with tag {tag.value!r}: {names}. "
            f"Only one is allowed."
        )
    return matches[0] if matches else None
