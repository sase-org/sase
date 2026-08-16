"""Host-owned adapter declarations used by Artifacts contract compilation."""

from __future__ import annotations

from dataclasses import dataclass

from ._artifact_tab_model import PaneEmptyState


GENERIC_DOCUMENT_COPY_TARGETS: tuple[str, ...] = (
    "reference",
    "link",
    "path",
    "title",
    "body",
    "json",
    "handoff",
    "snapshot",
)
PLAN_COPY_TARGETS: tuple[str, ...] = (
    "bead_id",
    "reference",
    "handoff",
    "design",
    "path",
    "title",
    "body",
    "link",
    "json",
    "snapshot",
)
GENERIC_DOCUMENT_COPY_KEYMAP_GROUP = "artifacts_documents"


@dataclass(frozen=True, slots=True)
class _BuiltinAdapter:
    """Host-owned fact table for one built-in Artifacts adapter."""

    adapter: str
    pane_id: str
    ref_kind: str | None
    target_prefix: str
    has_inventory: bool
    has_fields: bool
    has_stable_identity: bool
    has_revisions: bool
    can_mutate: bool
    is_plan_adapter: bool
    project_scoped: bool
    has_detail: bool
    copy_group: str
    copy_targets: tuple[str, ...]
    copy_keymap_group: str
    detail_fields: tuple[str, ...]
    detail_scroll_id: str | None
    empty_state: PaneEmptyState


BUILTIN_ADAPTERS: dict[str, _BuiltinAdapter] = {
    "stitches": _BuiltinAdapter(
        adapter="stitches",
        pane_id="stitches",
        ref_kind=None,
        target_prefix="commit",
        has_inventory=True,
        has_fields=True,
        has_stable_identity=True,
        has_revisions=False,
        can_mutate=False,
        is_plan_adapter=False,
        project_scoped=True,
        has_detail=True,
        copy_group="artifacts_stitches",
        copy_targets=(
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
        copy_keymap_group="artifacts_stitches",
        detail_fields=(),
        detail_scroll_id="stitches-detail-scroll",
        empty_state=PaneEmptyState(
            title="No stitches",
            body="No commits match the current project scope and filters.",
        ),
    ),
    "patches": _BuiltinAdapter(
        adapter="patches",
        pane_id="patches",
        ref_kind=None,
        target_prefix="patch",
        has_inventory=True,
        has_fields=True,
        has_stable_identity=True,
        has_revisions=False,
        can_mutate=True,
        is_plan_adapter=False,
        project_scoped=True,
        has_detail=True,
        copy_group="patches",
        copy_targets=(
            "raw",
            "with_snapshot",
            "bug",
            "pr_number",
            "name",
            "link",
            "spec",
            "reference",
            "snapshot",
        ),
        copy_keymap_group="patches",
        detail_fields=(),
        detail_scroll_id="detail-scroll",
        empty_state=PaneEmptyState(
            title="No patches",
            body="No patches match the current query.",
        ),
    ),
    "beads": _BuiltinAdapter(
        adapter="beads",
        pane_id="beads",
        ref_kind=None,
        target_prefix="bead",
        has_inventory=True,
        has_fields=True,
        has_stable_identity=True,
        has_revisions=False,
        can_mutate=True,
        is_plan_adapter=False,
        project_scoped=True,
        has_detail=True,
        copy_group="artifacts_beads",
        copy_targets=(
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
        copy_keymap_group="artifacts_beads",
        detail_fields=(),
        detail_scroll_id="beads-detail-scroll",
        empty_state=PaneEmptyState(
            title="No beads",
            body="No beads match the current project scope and filters.",
        ),
    ),
    "files": _BuiltinAdapter(
        adapter="files",
        pane_id="files",
        ref_kind=None,
        target_prefix="file",
        has_inventory=True,
        has_fields=True,
        has_stable_identity=True,
        has_revisions=True,
        can_mutate=False,
        is_plan_adapter=False,
        project_scoped=True,
        has_detail=True,
        copy_group="artifacts_other",
        copy_targets=(
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
        copy_keymap_group="artifacts_other",
        detail_fields=(),
        detail_scroll_id="files-detail-scroll",
        empty_state=PaneEmptyState(
            title="No artifact files",
            body="No artifact files match the current project scope and filters.",
        ),
    ),
}

PLAN_ADAPTER = _BuiltinAdapter(
    adapter="plan",
    pane_id="ref:plan",
    ref_kind="plan",
    target_prefix="plan",
    has_inventory=True,
    has_fields=True,
    has_stable_identity=True,
    has_revisions=False,
    can_mutate=False,
    is_plan_adapter=True,
    project_scoped=True,
    has_detail=True,
    copy_group="artifacts_plans",
    copy_targets=PLAN_COPY_TARGETS,
    copy_keymap_group="artifacts_plans",
    detail_fields=("tier", "title", "status"),
    detail_scroll_id="plans-detail-scroll",
    empty_state=PaneEmptyState(
        title="No plans",
        body="No plans match the current project scope and filters.",
    ),
)


__all__ = [
    "BUILTIN_ADAPTERS",
    "GENERIC_DOCUMENT_COPY_KEYMAP_GROUP",
    "GENERIC_DOCUMENT_COPY_TARGETS",
    "PLAN_ADAPTER",
    "PLAN_COPY_TARGETS",
]
