"""Shared vocabulary for every ACE copy-mode target."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


CopyTargetCategory = Literal["Identity", "Location", "Content", "Data", "Actions"]


@dataclass(frozen=True, slots=True)
class _CopyTarget:
    """Presentation metadata for one configured copy-mode target."""

    group: str
    target: str
    footer_label: str
    palette_label: str
    category: CopyTargetCategory
    plural_label: str
    accepts_marks: bool = False


def _target(
    group: str,
    target: str,
    footer_label: str,
    palette_label: str,
    category: CopyTargetCategory,
    plural_label: str,
    *,
    accepts_marks: bool = False,
) -> _CopyTarget:
    return _CopyTarget(
        group=group,
        target=target,
        footer_label=footer_label,
        palette_label=palette_label,
        category=category,
        plural_label=plural_label,
        accepts_marks=accepts_marks,
    )


COPY_TARGETS: tuple[_CopyTarget, ...] = (
    _target(
        "patches",
        "raw",
        "raw",
        "Copy raw line",
        "Content",
        "raw lines",
    ),
    _target(
        "patches",
        "with_snapshot",
        "+snap",
        "Copy line + snapshot",
        "Actions",
        "lines + snapshots",
    ),
    _target(
        "patches",
        "bug",
        "bug",
        "Copy bug id",
        "Identity",
        "bug ids",
    ),
    _target(
        "patches",
        "pr_number",
        "PR#",
        "Copy PR number",
        "Identity",
        "PR numbers",
    ),
    _target(
        "patches",
        "name",
        "name",
        "Copy Patch name",
        "Identity",
        "Patch names",
    ),
    _target(
        "patches",
        "link",
        "link",
        "Copy Markdown link",
        "Location",
        "Markdown links",
    ),
    _target(
        "patches",
        "spec",
        "spec",
        "Copy spec text",
        "Content",
        "spec texts",
    ),
    _target(
        "patches",
        "snapshot",
        "snap",
        "Copy snapshot",
        "Actions",
        "snapshots",
    ),
    _target(
        "artifacts_stitches",
        "sha",
        "SHA",
        "Copy commit SHA",
        "Identity",
        "commit SHAs",
        accepts_marks=True,
    ),
    _target(
        "artifacts_stitches",
        "reference",
        "@ref",
        "Copy artifact reference",
        "Identity",
        "artifact references",
        accepts_marks=True,
    ),
    _target(
        "artifacts_stitches",
        "link",
        "link",
        "Copy Markdown link",
        "Location",
        "Markdown links",
        accepts_marks=True,
    ),
    _target(
        "artifacts_stitches",
        "message",
        "message",
        "Copy commit message",
        "Content",
        "commit messages",
        accepts_marks=True,
    ),
    _target(
        "artifacts_stitches",
        "repo_sha",
        "repo@SHA",
        "Copy repo@SHA",
        "Identity",
        "repository commit references",
        accepts_marks=True,
    ),
    _target(
        "artifacts_stitches",
        "plan",
        "plan ref",
        "Copy linked plan reference",
        "Location",
        "linked plan references",
        accepts_marks=True,
    ),
    _target(
        "artifacts_stitches",
        "json",
        "JSON",
        "Copy metadata JSON",
        "Data",
        "metadata JSON records",
        accepts_marks=True,
    ),
    _target(
        "artifacts_stitches",
        "handoff",
        "agent + @ref",
        "Reference in new agent prompt",
        "Actions",
        "references in a new agent prompt",
        accepts_marks=True,
    ),
    _target(
        "artifacts_stitches",
        "snapshot",
        "snap",
        "Copy Artifacts snapshot",
        "Actions",
        "Artifacts snapshots",
    ),
    _target(
        "artifacts_plans",
        "bead_id",
        "bead id",
        "Copy owning bead id",
        "Identity",
        "owning bead ids",
        accepts_marks=True,
    ),
    _target(
        "artifacts_plans",
        "reference",
        "@ref",
        "Copy artifact reference",
        "Identity",
        "artifact references",
        accepts_marks=True,
    ),
    _target(
        "artifacts_plans",
        "link",
        "link",
        "Copy Markdown link",
        "Location",
        "Markdown links",
        accepts_marks=True,
    ),
    _target(
        "artifacts_plans",
        "design",
        "design",
        "Copy design reference",
        "Location",
        "design references",
        accepts_marks=True,
    ),
    _target(
        "artifacts_plans",
        "path",
        "path",
        "Copy plan path",
        "Location",
        "plan paths",
        accepts_marks=True,
    ),
    _target(
        "artifacts_plans",
        "title",
        "title",
        "Copy plan title",
        "Identity",
        "plan titles",
        accepts_marks=True,
    ),
    _target(
        "artifacts_plans",
        "body",
        "body",
        "Copy plan body",
        "Content",
        "plan bodies",
        accepts_marks=True,
    ),
    _target(
        "artifacts_plans",
        "json",
        "JSON",
        "Copy metadata JSON",
        "Data",
        "metadata JSON records",
        accepts_marks=True,
    ),
    _target(
        "artifacts_plans",
        "handoff",
        "agent + @ref",
        "Reference in new agent prompt",
        "Actions",
        "references in a new agent prompt",
        accepts_marks=True,
    ),
    _target(
        "artifacts_plans",
        "snapshot",
        "snap",
        "Copy Artifacts snapshot",
        "Actions",
        "Artifacts snapshots",
    ),
    _target(
        "artifacts_beads",
        "id",
        "id",
        "Copy bead id",
        "Identity",
        "bead ids",
        accepts_marks=True,
    ),
    _target(
        "artifacts_beads",
        "reference",
        "@ref",
        "Copy artifact reference",
        "Identity",
        "artifact references",
        accepts_marks=True,
    ),
    _target(
        "artifacts_beads",
        "link",
        "link",
        "Copy Markdown link",
        "Location",
        "Markdown links",
        accepts_marks=True,
    ),
    _target(
        "artifacts_beads",
        "title",
        "title",
        "Copy bead title",
        "Identity",
        "bead titles",
        accepts_marks=True,
    ),
    _target(
        "artifacts_beads",
        "body",
        "body",
        "Copy bead body",
        "Content",
        "bead bodies",
        accepts_marks=True,
    ),
    _target(
        "artifacts_beads",
        "design",
        "design",
        "Copy design reference",
        "Location",
        "design references",
        accepts_marks=True,
    ),
    _target(
        "artifacts_beads",
        "json",
        "JSON",
        "Copy metadata JSON",
        "Data",
        "metadata JSON records",
        accepts_marks=True,
    ),
    _target(
        "artifacts_beads",
        "handoff",
        "agent + @ref",
        "Reference in new agent prompt",
        "Actions",
        "references in a new agent prompt",
        accepts_marks=True,
    ),
    _target(
        "artifacts_beads",
        "snapshot",
        "snap",
        "Copy Artifacts snapshot",
        "Actions",
        "Artifacts snapshots",
    ),
    _target(
        "artifacts_chats",
        "reference",
        "@ref",
        "Copy artifact reference",
        "Identity",
        "artifact references",
        accepts_marks=True,
    ),
    _target(
        "artifacts_chats",
        "link",
        "link",
        "Copy Markdown link",
        "Location",
        "Markdown links",
        accepts_marks=True,
    ),
    _target(
        "artifacts_chats",
        "path",
        "path",
        "Copy chat path",
        "Location",
        "chat paths",
        accepts_marks=True,
    ),
    _target(
        "artifacts_chats",
        "agent",
        "agent",
        "Copy chat agent name",
        "Identity",
        "chat agent names",
        accepts_marks=True,
    ),
    _target(
        "artifacts_chats",
        "transcript",
        "transcript",
        "Copy chat transcript",
        "Content",
        "chat transcripts",
        accepts_marks=True,
    ),
    _target(
        "artifacts_chats",
        "json",
        "JSON",
        "Copy metadata JSON",
        "Data",
        "metadata JSON records",
        accepts_marks=True,
    ),
    _target(
        "artifacts_chats",
        "handoff",
        "agent + @ref",
        "Reference in new agent prompt",
        "Actions",
        "references in a new agent prompt",
        accepts_marks=True,
    ),
    _target(
        "artifacts_chats",
        "snapshot",
        "snap",
        "Copy Artifacts snapshot",
        "Actions",
        "Artifacts snapshots",
    ),
    _target(
        "artifacts_other",
        "contents",
        "contents",
        "Copy artifact-file contents",
        "Content",
        "artifact-file contents",
        accepts_marks=True,
    ),
    _target(
        "artifacts_other",
        "reference",
        "@ref",
        "Copy artifact reference",
        "Identity",
        "artifact references",
        accepts_marks=True,
    ),
    _target(
        "artifacts_other",
        "link",
        "link",
        "Copy Markdown link",
        "Location",
        "Markdown links",
        accepts_marks=True,
    ),
    _target(
        "artifacts_other",
        "path",
        "path",
        "Copy stored path",
        "Location",
        "stored paths",
        accepts_marks=True,
    ),
    _target(
        "artifacts_other",
        "source",
        "source",
        "Copy source path",
        "Location",
        "source paths",
        accepts_marks=True,
    ),
    _target(
        "artifacts_other",
        "label",
        "label",
        "Copy artifact-file label",
        "Identity",
        "artifact-file labels",
        accepts_marks=True,
    ),
    _target(
        "artifacts_other",
        "json",
        "JSON",
        "Copy metadata JSON",
        "Data",
        "metadata JSON records",
        accepts_marks=True,
    ),
    _target(
        "artifacts_other",
        "handoff",
        "agent + @ref",
        "Reference in new agent prompt",
        "Actions",
        "references in a new agent prompt",
        accepts_marks=True,
    ),
    _target(
        "artifacts_other",
        "snapshot",
        "snap",
        "Copy Artifacts snapshot",
        "Actions",
        "Artifacts snapshots",
    ),
    _target("agents", "chat", "chat", "Copy chat path", "Location", "chat paths"),
    _target(
        "agents",
        "file_path",
        "file path",
        "Copy file path",
        "Location",
        "file paths",
    ),
    _target(
        "agents",
        "name",
        "name",
        "Copy agent name",
        "Identity",
        "agent names",
    ),
    _target(
        "agents",
        "prompt",
        "prompt",
        "Copy prompt",
        "Content",
        "prompts",
    ),
    _target(
        "agents",
        "reference",
        "@ref",
        "Copy agent reference",
        "Identity",
        "agent references",
    ),
    _target(
        "agents",
        "snapshot",
        "snap",
        "Copy snapshot",
        "Actions",
        "snapshots",
    ),
    _target(
        "axe",
        "visible",
        "visible",
        "Copy visible output",
        "Content",
        "visible outputs",
    ),
    _target(
        "axe",
        "full",
        "full",
        "Copy full output",
        "Content",
        "full outputs",
    ),
    _target(
        "axe",
        "snapshot",
        "snap",
        "Copy snapshot",
        "Actions",
        "snapshots",
    ),
)

_TARGETS_BY_KEY = {(item.group, item.target): item for item in COPY_TARGETS}


def _normalize_copy_group(group: str) -> str:
    """Return the canonical copy-mode group id."""
    if group.startswith("artifacts_ref:"):
        return "artifacts_plans"
    if group == "artifacts_files":
        return "artifacts_other"
    return "patches" if group == "patches" else group


def copy_targets_for(group: str) -> tuple[_CopyTarget, ...]:
    """Return the registry entries for *group* in presentation order."""

    group = _normalize_copy_group(group)
    return tuple(item for item in COPY_TARGETS if item.group == group)


def copy_target_for(group: str, target: str) -> _CopyTarget | None:
    """Return one target, preserving the legacy Patch alias."""

    group = _normalize_copy_group(group)
    if group == "patches" and target == "cl_number":
        target = "pr_number"
    return _TARGETS_BY_KEY.get((group, target))


__all__ = [
    "COPY_TARGETS",
    "CopyTargetCategory",
    "copy_target_for",
    "copy_targets_for",
]
