"""Registry and key-dispatch assembly for Copy as palette contexts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...commands import (
    CommandContext,
    build_command_catalog,
    is_command_available,
)
from ...copy_targets import copy_targets_for
from ...keymaps import footer_key_display
from ._palette_helpers import shorten

if TYPE_CHECKING:
    from ...modals.copy_as_types import CopyAsContext


_DISPATCH_ORDER: dict[str, tuple[str, ...]] = {
    "patches": (
        "raw",
        "with_snapshot",
        "bug",
        "pr_number",
        "name",
        "link",
        "spec",
        "snapshot",
    ),
    "artifacts_stitches": (
        "snapshot",
        "reference",
        "handoff",
        "link",
        "json",
        "sha",
        "message",
        "repo_sha",
        "plan",
    ),
    "artifacts_plans": (
        "snapshot",
        "reference",
        "handoff",
        "link",
        "json",
        "bead_id",
        "design",
        "path",
        "title",
        "body",
    ),
    "artifacts_beads": (
        "snapshot",
        "reference",
        "handoff",
        "link",
        "json",
        "id",
        "title",
        "body",
        "design",
    ),
    "artifacts_chats": (
        "snapshot",
        "reference",
        "handoff",
        "link",
        "json",
        "path",
        "agent",
        "transcript",
    ),
    "artifacts_other": (
        "snapshot",
        "reference",
        "handoff",
        "link",
        "json",
        "contents",
        "path",
        "source",
        "label",
    ),
    "artifacts_bugs": (
        "snapshot",
        "reference",
        "handoff",
        "link",
        "json",
        "number",
        "url",
        "title",
        "prompt",
    ),
    "agents": ("chat", "file_path", "name", "prompt", "reference", "snapshot"),
    "axe": ("visible", "full", "snapshot"),
}


def context_from_registry(
    app: Any,
    *,
    group: str,
    command_context: CommandContext,
    subtitle: str,
    unknown_context: str,
    previews: dict[str, str],
    marked: bool = False,
) -> CopyAsContext | None:
    from ...modals.copy_as_types import CopyAsContext, CopyAsRow

    keys = app._keymap_registry.copy_mode.keys.get(group, {})
    if not isinstance(keys, dict):
        return None

    catalog = {
        spec.id: spec
        for spec in build_command_catalog(app._keymap_registry)
        if spec.executor.kind == "copy_mode_key"
    }
    dispatch_winners = _dispatch_winners(group, keys)
    rows: list[CopyAsRow] = []
    for target in copy_targets_for(group):
        key = keys.get(target.target)
        spec_id = f"copy.{group}.{target.target}"
        if target.target == "pr_number" and not isinstance(key, str):
            key = keys.get("cl_number")
            spec_id = f"copy.{group}.cl_number"
        if not isinstance(key, str):
            continue
        if dispatch_winners.get(key) != target.target:
            continue
        spec = catalog.get(spec_id)
        if spec is None or not is_command_available(spec, command_context):
            continue
        label = (
            target.plural_label
            if marked and target.accepts_marks
            else target.palette_label
        )
        rows.append(
            CopyAsRow(
                key=key,
                key_display=footer_key_display(key),
                target=target.target,
                label=label,
                category=target.category,
                preview=previews.get(target.target, ""),
            )
        )
    if not rows:
        return None
    return CopyAsContext(
        group=group,
        subtitle=shorten(subtitle, limit=92),
        unknown_context=unknown_context,
        rows=tuple(rows),
    )


def _dispatch_winners(group: str, keys: dict[str, str]) -> dict[str, str]:
    winners: dict[str, str] = {}
    for target in _DISPATCH_ORDER.get(group, ()):
        key = keys.get(target)
        if target == "pr_number" and not isinstance(key, str):
            key = keys.get("cl_number")
        if isinstance(key, str):
            winners.setdefault(key, target)
    return winners
