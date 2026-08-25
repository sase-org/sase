"""Host-owned adapter declarations used by Artifacts contract compilation."""

from __future__ import annotations

from dataclasses import dataclass

from ._artifact_tab_model import (
    PaneEmptyState,
    PaneGroupingDecl,
    PaneGroupingModeDecl,
    PaneRelationDecl,
    PaneStatusCounter,
    RelationKind,
)


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

PROVIDER_BUNDLE_RELATION = PaneRelationDecl(
    name="bundle",
    kind=RelationKind.FAMILY,
    label="Bundle",
    source="document_filename_family",
    target_pane=None,
    inverse=None,
    directed=False,
    transitive=False,
)


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
    relations: tuple[PaneRelationDecl, ...]
    grouping: PaneGroupingDecl
    status_counters: tuple[PaneStatusCounter, ...]
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
        relations=(
            PaneRelationDecl(
                name="parents",
                kind=RelationKind.HIERARCHY,
                label="Parents",
                source="vcs_commit_parent_ids",
                target_pane=None,
                inverse="children",
                directed=True,
                transitive=True,
            ),
            PaneRelationDecl(
                name="children",
                kind=RelationKind.HIERARCHY,
                label="Children",
                source="vcs_commit_parent_ids",
                target_pane=None,
                inverse="parents",
                directed=True,
                transitive=True,
            ),
            PaneRelationDecl(
                name="patches",
                kind=RelationKind.LINK,
                label="Patches",
                source="stitch_patch_tag",
                target_pane="patches",
                inverse="stitches",
                directed=True,
                transitive=False,
            ),
        ),
        grouping=PaneGroupingDecl(
            modes=(
                PaneGroupingModeDecl(
                    id="by_date",
                    label="Date",
                    keys=("committed_date",),
                ),
                PaneGroupingModeDecl(
                    id="by_repo",
                    label="Repository",
                    keys=("repo",),
                ),
                PaneGroupingModeDecl(
                    id="by_author",
                    label="Author",
                    keys=("author",),
                ),
            ),
            default_mode="by_date",
        ),
        status_counters=(),
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
        relations=(
            PaneRelationDecl(
                name="ancestors",
                kind=RelationKind.HIERARCHY,
                label="Ancestors",
                source="patch_parent",
                target_pane=None,
                inverse="children",
                directed=True,
                transitive=True,
            ),
            PaneRelationDecl(
                name="children",
                kind=RelationKind.HIERARCHY,
                label="Children",
                source="patch_parent",
                target_pane=None,
                inverse="ancestors",
                directed=True,
                transitive=True,
            ),
            PaneRelationDecl(
                name="siblings",
                kind=RelationKind.FAMILY,
                label="Siblings",
                source="patch_revert_family",
                target_pane=None,
                inverse=None,
                directed=False,
                transitive=False,
            ),
        ),
        grouping=PaneGroupingDecl(
            modes=(
                PaneGroupingModeDecl(
                    id="by_project",
                    label="Project",
                    keys=("project", "family"),
                ),
                PaneGroupingModeDecl(
                    id="by_date",
                    label="Date",
                    keys=("latest_timestamp",),
                ),
                PaneGroupingModeDecl(
                    id="by_status",
                    label="Status",
                    keys=("status", "family"),
                ),
            ),
            default_mode="by_project",
        ),
        status_counters=(PaneStatusCounter(name="status", field="status"),),
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
        relations=(
            PaneRelationDecl(
                name="parent",
                kind=RelationKind.HIERARCHY,
                label="Parent",
                source="bead_parent_id",
                target_pane=None,
                inverse="children",
                directed=True,
                transitive=True,
            ),
            PaneRelationDecl(
                name="children",
                kind=RelationKind.HIERARCHY,
                label="Children",
                source="bead_parent_id",
                target_pane=None,
                inverse="parent",
                directed=True,
                transitive=True,
            ),
            PaneRelationDecl(
                name="plans",
                kind=RelationKind.LINK,
                label="Plans",
                source="bead_plan_links",
                target_pane="ref:plan",
                inverse="beads",
                directed=True,
                transitive=False,
            ),
            PaneRelationDecl(
                name="dependencies",
                kind=RelationKind.LINK,
                label="Dependencies",
                source="bead_dependencies",
                target_pane=None,
                inverse="dependents",
                directed=True,
                transitive=False,
            ),
        ),
        # Empty: the Beads pane only implements the single-purpose
        # epic-tree fold (``beads_expand``/``beads_collapse`` over its own
        # ``_epic_fold_registry``), not the multi-mode
        # ``ArtifactGroupFoldMixin`` protocol (``group_cycle_mode`` etc.)
        # that ``PaneCapability.GROUPING`` promises. Declaring modes here
        # without that implementation is exactly the "claims a feature its
        # data cannot support" case the contract rules exist to prevent
        # (sase-m6.9). See that bead's PROPOSED FOLLOW-UP for real
        # by_epic/by_status/by_type support.
        grouping=PaneGroupingDecl(),
        status_counters=(PaneStatusCounter(name="status", field="status"),),
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
            "bug",
        ),
        copy_keymap_group="artifacts_beads",
        detail_fields=(),
        detail_scroll_id="beads-detail-scroll",
        empty_state=PaneEmptyState(
            title="No beads",
            body="No beads match the current project scope and filters.",
        ),
    ),
    "agents": _BuiltinAdapter(
        adapter="agents",
        pane_id="agents",
        ref_kind=None,
        target_prefix="agent",
        has_inventory=True,
        # False: FILTER_SESSION/QUERY_HISTORY/SAVED_QUERIES need
        # ``AgentFilterBar`` and an ``action_edit_query`` branch for this
        # pane, which is the ``query`` phase's job (sase-tj.5). Flipping
        # this before that lands would declare a capability whose key
        # silently no-ops, the same anti-pattern the ``beads`` grouping
        # comment above documents.
        has_fields=False,
        has_stable_identity=True,
        has_revisions=False,
        can_mutate=True,
        is_plan_adapter=False,
        project_scoped=True,
        has_detail=True,
        relations=(
            PaneRelationDecl(
                name="family",
                kind=RelationKind.HIERARCHY,
                label="Family",
                source="agent_family_container",
                target_pane=None,
                inverse=None,
                directed=True,
                transitive=False,
            ),
            PaneRelationDecl(
                name="clan",
                kind=RelationKind.HIERARCHY,
                label="Clan",
                source="agent_clan_container",
                target_pane=None,
                inverse=None,
                directed=True,
                transitive=False,
            ),
            PaneRelationDecl(
                name="parent",
                kind=RelationKind.HIERARCHY,
                label="Parent",
                source="agent_parent_timestamp",
                target_pane=None,
                inverse=None,
                directed=True,
                transitive=False,
            ),
            PaneRelationDecl(
                name="retry_chain",
                kind=RelationKind.FAMILY,
                label="Retry chain",
                source="agent_retry_chain",
                target_pane=None,
                inverse=None,
                directed=False,
                transitive=False,
            ),
        ),
        grouping=PaneGroupingDecl(
            modes=(
                PaneGroupingModeDecl(
                    id="by_family",
                    label="Family",
                    keys=("family",),
                ),
                PaneGroupingModeDecl(
                    id="by_state",
                    label="State",
                    keys=("state",),
                ),
                PaneGroupingModeDecl(
                    id="by_project",
                    label="Project",
                    keys=("project",),
                ),
            ),
            default_mode="by_family",
        ),
        status_counters=(PaneStatusCounter(name="status", field="status"),),
        copy_group="artifacts_agents",
        copy_targets=(
            "reference",
            "name",
            "link",
            "path",
            "chat",
            "prompt",
            "json",
            "handoff",
            "snapshot",
        ),
        copy_keymap_group="artifacts_agents",
        detail_fields=(),
        detail_scroll_id="agents-detail-scroll",
        empty_state=PaneEmptyState(
            title="No agents",
            body="No agents match the current project scope and filters.",
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
        relations=(
            PaneRelationDecl(
                name="versions",
                kind=RelationKind.FAMILY,
                label="Versions",
                source="artifact_file_versions",
                target_pane=None,
                inverse=None,
                directed=False,
                transitive=False,
            ),
        ),
        grouping=PaneGroupingDecl(
            modes=(
                PaneGroupingModeDecl(
                    id="by_source",
                    label="Source",
                    keys=("origin",),
                ),
                PaneGroupingModeDecl(
                    id="by_kind",
                    label="Kind",
                    keys=("kind",),
                ),
                PaneGroupingModeDecl(
                    id="by_project",
                    label="Project",
                    keys=("project",),
                ),
            ),
            default_mode="by_source",
        ),
        status_counters=(),
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
    relations=(
        PaneRelationDecl(
            name="parent",
            kind=RelationKind.HIERARCHY,
            label="Parent",
            source="plan_parent",
            target_pane=None,
            inverse="children",
            directed=True,
            transitive=True,
        ),
        PaneRelationDecl(
            name="children",
            kind=RelationKind.HIERARCHY,
            label="Children",
            source="plan_parent",
            target_pane=None,
            inverse="parent",
            directed=True,
            transitive=True,
        ),
        PaneRelationDecl(
            name="beads",
            kind=RelationKind.LINK,
            label="Beads",
            source="plan_bead_links",
            target_pane="beads",
            inverse="plans",
            directed=True,
            transitive=False,
        ),
    ),
    grouping=PaneGroupingDecl(
        modes=(
            PaneGroupingModeDecl(
                id="by_kind",
                label="Kind",
                keys=("kind", "tier"),
            ),
            PaneGroupingModeDecl(
                id="by_status",
                label="Status",
                keys=("status",),
            ),
            PaneGroupingModeDecl(
                id="by_project",
                label="Project",
                keys=("project",),
            ),
        ),
        default_mode="by_kind",
    ),
    status_counters=(PaneStatusCounter(name="status", field="status"),),
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
    "PROVIDER_BUNDLE_RELATION",
]
