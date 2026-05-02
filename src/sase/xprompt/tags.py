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
    propose = "propose"
    make_mentor_changes = "make_mentor_changes"
    diff_file = "diff_file"
    append_to_pr = "append_to_pr"
    append_to_commit_and_propose = "append_to_commit_and_propose"
    memory = "memory"
    create_epic_bead = "create_epic_bead"
    create_legend_bead = "create_legend_bead"
    work_phase_bead = "work_phase_bead"
    land_epic = "land_epic"


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


def _extract_plugin_module(source_path: str | None) -> str | None:
    """Extract the plugin module name from an xprompt/workflow source_path."""
    if not source_path:
        return None
    if source_path.startswith("plugin:"):
        # "plugin:sase_github/gh.yml" → "sase_github"
        return source_path.removeprefix("plugin:").split("/")[0]
    if source_path.startswith("plugin_config:"):
        # "plugin_config:sase_google" → "sase_google"
        return source_path.removeprefix("plugin_config:")
    return None


def get_by_tag(
    tag: XPromptTag,
    project: str | None = None,
    vcs_hint: str | None = None,
) -> Workflow | None:
    """Find the highest-priority xprompt/workflow with the given tag.

    Uses ``get_all_prompts()`` so the loader's existing precedence
    (local > user > plugin > builtin) naturally handles override order.
    The dict is built from lowest to highest priority, so we return the
    **last** match to respect the override chain.

    When *vcs_hint* is provided and multiple workflows match the tag,
    the result is disambiguated by preferring the match whose plugin
    module matches the active VCS workflow's plugin module.

    Returns the highest-priority matching Workflow, or None.
    """
    from sase.xprompt.loader import get_all_prompts

    all_prompts = get_all_prompts(project=project)

    matches: list[Workflow] = []
    for wf in all_prompts.values():
        if tag in wf.tags:
            matches.append(wf)

    if not matches:
        return None
    if len(matches) == 1 or not vcs_hint:
        return matches[-1]

    # Disambiguate: prefer the match from the same plugin as the VCS workflow
    vcs_wf = all_prompts.get(vcs_hint)
    if vcs_wf is None:
        return matches[-1]

    vcs_module = _extract_plugin_module(vcs_wf.source_path)
    if vcs_module is None:
        return matches[-1]

    for match in reversed(matches):
        if _extract_plugin_module(match.source_path) == vcs_module:
            return match

    return matches[-1]


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
