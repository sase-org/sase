"""Sibling Patch revert logic for status transitions."""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console

logger = logging.getLogger(__name__)


@dataclass
class SiblingRevertResult:
    """Result of reverting a sibling Draft Patch."""

    name: str
    success: bool
    error: str | None = None


def revert_sibling_draft_patches(
    project_file: str,
    base_name: str,
    excluded_name: str,
    console: "Console | None" = None,
) -> list[SiblingRevertResult]:
    """Revert all WIP/Draft Patches with the same basename.

    When a WIP/Draft Patch transitions to Ready and has its suffix stripped,
    any other WIP/Draft Patches with the same base name are automatically
    reverted since they are now obsolete.

    Args:
        project_file: Path to the project file.
        base_name: The base name without suffix (e.g., "foo_bar").
        excluded_name: The original suffixed name that was just transitioned
            (don't revert this one).
        console: Optional Rich console for output.

    Returns:
        List of SiblingRevertResult for each sibling that was attempted to be
        reverted.
    """
    from sase.ace.patch import parse_project_file
    from sase.ace.revert import revert_patch
    from sase.core.patch import strip_reverted_suffix

    patches = parse_project_file(project_file)
    results: list[SiblingRevertResult] = []

    for cs in patches:
        # Skip the one we just transitioned
        if cs.name == excluded_name:
            continue

        # Check if same basename and is WIP or Draft
        cs_base = strip_reverted_suffix(cs.name)
        if cs_base == base_name and cs.status in ("WIP", "Draft"):
            logger.info(f"Auto-reverting sibling Patch: {cs.name} ({cs.status})")
            if console:
                from sase.project_display_names import humanize_cl_name

                console.print(
                    f"[yellow]Auto-reverting sibling {cs.status}:[/] "
                    f"{humanize_cl_name(cs.name)}"
                )
            success, error = revert_patch(cs, console=console)
            if not success:
                logger.warning(f"Failed to revert {cs.name}: {error}")
            results.append(
                SiblingRevertResult(name=cs.name, success=success, error=error)
            )

    return results
