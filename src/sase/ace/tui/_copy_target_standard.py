"""Static copy targets for non-artifact ACE tabs."""

from __future__ import annotations

from ._copy_target_types import CopyTarget, build_copy_target


PATCH_COPY_TARGETS: tuple[CopyTarget, ...] = (
    build_copy_target(
        "patches",
        "raw",
        "raw",
        "Copy raw line",
        "Content",
        "raw lines",
    ),
    build_copy_target(
        "patches",
        "with_snapshot",
        "+snap",
        "Copy line + snapshot",
        "Actions",
        "lines + snapshots",
    ),
    build_copy_target(
        "patches",
        "bug",
        "bug",
        "Copy bug id",
        "Identity",
        "bug ids",
    ),
    build_copy_target(
        "patches",
        "pr_number",
        "PR#",
        "Copy PR number",
        "Identity",
        "PR numbers",
    ),
    build_copy_target(
        "patches",
        "name",
        "name",
        "Copy Patch name",
        "Identity",
        "Patch names",
    ),
    build_copy_target(
        "patches",
        "link",
        "link",
        "Copy Markdown link",
        "Location",
        "Markdown links",
    ),
    build_copy_target(
        "patches",
        "spec",
        "spec",
        "Copy spec text",
        "Content",
        "spec texts",
    ),
    build_copy_target(
        "patches",
        "reference",
        "@ref",
        "Copy @patch reference",
        "Identity",
        "Patch references",
        accepts_marks=True,
    ),
    build_copy_target(
        "patches",
        "snapshot",
        "snap",
        "Copy snapshot",
        "Actions",
        "snapshots",
    ),
)

AGENT_COPY_TARGETS: tuple[CopyTarget, ...] = (
    build_copy_target(
        "agents", "chat", "chat", "Copy chat path", "Location", "chat paths"
    ),
    build_copy_target(
        "agents",
        "file_path",
        "file path",
        "Copy file path",
        "Location",
        "file paths",
    ),
    build_copy_target(
        "agents",
        "name",
        "name",
        "Copy agent name",
        "Identity",
        "agent names",
    ),
    build_copy_target(
        "agents",
        "prompt",
        "prompt",
        "Copy prompt",
        "Content",
        "prompts",
    ),
    build_copy_target(
        "agents",
        "reference",
        "@ref",
        "Copy agent reference",
        "Identity",
        "agent references",
    ),
    build_copy_target(
        "agents",
        "snapshot",
        "snap",
        "Copy snapshot",
        "Actions",
        "snapshots",
    ),
)

AXE_COPY_TARGETS: tuple[CopyTarget, ...] = (
    build_copy_target(
        "axe",
        "visible",
        "visible",
        "Copy visible output",
        "Content",
        "visible outputs",
    ),
    build_copy_target(
        "axe",
        "full",
        "full",
        "Copy full output",
        "Content",
        "full outputs",
    ),
    build_copy_target(
        "axe",
        "snapshot",
        "snap",
        "Copy snapshot",
        "Actions",
        "snapshots",
    ),
)


__all__ = [
    "AGENT_COPY_TARGETS",
    "AXE_COPY_TARGETS",
    "PATCH_COPY_TARGETS",
]
