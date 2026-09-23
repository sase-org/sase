"""Patches pane hosted inside the shared Artifacts chrome."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll

from sase.ace.query_profile import compiled_profile_for_builtin_pane
from sase.core.artifact_relations import RelationIndex

from ..._artifact_tab_model import ArtifactsPaneContract
from ..patch_detail import PatchDetail
from ..patch_info_panel import PatchInfoPanel
from ..patch_list import PatchList
from ..tab_quickstart import TabQuickStart
from .entry_navigation import (
    ArtifactEntryNavigator,
    ArtifactEntryTarget,
    LinkRequestState,
)
from .lifecycle import ArtifactsPaneLifecycle
from .patch_entry import patch_row_target
from .patch_filter_bar import PatchFilterBar
from .patches_filter_session import PatchesFilterSessionMixin
from .patches_probe import (
    PatchMembershipProbe,
    patch_relation_status_hidden,
    patch_stack_size,
)
from .relation_panel import (
    RelationEntryFact,
    RelationPanel,
    RelationPanelHostMixin,
    RelationRole,
)


class ArtifactsPatchesPane(
    PatchesFilterSessionMixin,
    RelationPanelHostMixin,
    ArtifactEntryNavigator,
    ArtifactsPaneLifecycle,
    Vertical,
):
    """The specialized Patch surface hosted inside the shared Artifacts chrome."""

    _pending_entry_target: ArtifactEntryTarget | None
    _pending_entry_generation: int | None

    def __init__(
        self,
        *,
        contract: ArtifactsPaneContract | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._init_artifacts_lifecycle()
        self._init_patches_filter_session()
        self.contract = contract
        self._query_profile = (
            contract.query_profile
            if contract is not None
            else compiled_profile_for_builtin_pane("patches")
        )

    def compose(self) -> ComposeResult:
        profile = (
            self.contract.query_profile
            if self.contract is not None
            else compiled_profile_for_builtin_pane("patches")
        )
        yield PatchFilterBar(id="patch-filter-bar", profile=profile)
        with Horizontal(id="patch-panels"):
            with Vertical(id="list-container"):
                yield PatchInfoPanel(id="info-panel")
                yield PatchList(id="list-panel")
                yield RelationPanel(
                    id="patches-relation-panel",
                    classes="artifacts-relation-panel",
                )
            with Vertical(id="detail-container"):
                with VerticalScroll(id="detail-scroll"):
                    yield PatchDetail(id="detail-panel")
                yield TabQuickStart(
                    tab="artifacts",
                    id="patch-quickstart-panel",
                    classes="hidden",
                )

    def on_activate(self) -> None:
        """Restore focus to the PR surface after another pane owned it."""
        if self.is_mounted:
            self.query_one("#list-panel", PatchList).focus()

    def entry_targets(self) -> tuple[ArtifactEntryTarget, ...]:
        """Return visible Patch row identities in visual order.

        Members hidden under a collapsed group banner are not stops: like
        the other panes' rendered-row indexes, this is what lets the
        link-follow Fold step (and the same-pane fast path) tell a hidden
        row from a visible one.
        """
        app = cast(Any, self.app)
        patches = tuple(getattr(app, "patches", ()))
        visible = self._visible_patch_indices()
        if visible is None:
            return tuple(patch_row_target(patch) for patch in patches)
        return tuple(
            patch_row_target(patch)
            for index, patch in enumerate(patches)
            if index in visible
        )

    def selected_entry_target(self) -> ArtifactEntryTarget | None:
        app = cast(Any, self.app)
        patches = getattr(app, "patches", ())
        idx = getattr(app, "current_idx", 0)
        if not patches or not 0 <= idx < len(patches):
            return None
        return patch_row_target(patches[idx])

    def select_entry_target(self, target: ArtifactEntryTarget) -> bool:
        """Resolve *target* against the current Patch list and focus it.

        Clears any active banner focus — selecting a concrete Patch row
        always wins over a collapsed group banner — and synchronously
        focuses the Patch list so the row is immediately interactive.
        """
        app = cast(Any, self.app)
        patches = getattr(app, "patches", ())
        for index, patch in enumerate(patches):
            if patch_row_target(patch) != target:
                continue
            app._current_patch_group_key = None
            app.current_idx = index
            if self.is_mounted:
                self.query_one("#list-panel", PatchList).focus()
            return True
        return False

    def request_entry_target(
        self,
        target: ArtifactEntryTarget,
        *,
        generation: int | None = None,
    ) -> LinkRequestState:
        """Select *target* now.

        Unlike the async-loaded non-PR panes, Patches are already loaded
        into app state by the time this pane can be queried, so there is
        no later row model to defer to — a miss here means the Patch is
        genuinely not in the current filtered list, or it hides under a
        collapsed group banner (the link-follow Fold step expands it).
        """
        if self.select_entry_target(target):
            if self._patch_target_visible_in_list(target):
                self._pending_entry_generation = generation
                return self._complete_entry_request(LinkRequestState.SELECTED)
            self._pending_entry_target = target
            self._pending_entry_generation = generation
            return self._complete_entry_request(LinkRequestState.MISSING)
        return LinkRequestState.MISSING

    def _visible_patch_indices(self) -> frozenset[int] | None:
        """Return visible list positions, or ``None`` when unknown.

        ``None`` (no grouping mode, no registry, or any helper failure)
        means "treat every row as visible", so selection never breaks on a
        helper error.
        """
        try:
            app = cast(Any, self.app)
            patches = list(getattr(app, "patches", ()))
            mode = getattr(app, "_patch_grouping_mode", None)
            registry = getattr(app, "_patch_group_fold_registry", None)
            if mode is None or registry is None:
                return None
            from ...models.patch_groups import build_patch_tree

            entries = build_patch_tree(patches, mode=mode, fold_registry=registry)
            return frozenset(
                entry.patch_idx
                for entry in entries
                if entry.kind == "patch" and entry.patch_idx is not None
            )
        except Exception:  # noqa: BLE001 - never break selection on a helper error
            return None

    def _patch_target_visible_in_list(self, target: ArtifactEntryTarget) -> bool:
        """Return whether *target* has a visible row in the grouped list."""
        app = cast(Any, self.app)
        patches = tuple(getattr(app, "patches", ()))
        index = next(
            (
                position
                for position, patch in enumerate(patches)
                if patch_row_target(patch) == target
            ),
            None,
        )
        if index is None:
            return False
        visible = self._visible_patch_indices()
        return visible is None or index in visible

    def host_query_row_for_target(self, target: ArtifactEntryTarget) -> Any | None:
        """Return the Patch object backing *target* from the unfiltered inventory."""
        if target.pane_id != "patches":
            return None
        app = cast(Any, self.app)
        for patch in getattr(app, "_all_patches", ()):
            if patch_row_target(patch) == target:
                return patch
        return None

    def expand_fold_for_entry_target(self, target: ArtifactEntryTarget) -> bool:
        """Expand the minimum Patch group banner hiding *target*.

        Unlike the async-loaded panes, Patches render their groups from the
        already-filtered list, so selecting a member of a collapsed group
        leaves the highlight on a hidden row. Expanding the target's own
        enclosing banners first lets the re-request select it for real.
        """
        if target.pane_id != "patches" or len(target.parts) < 2:
            return False
        app = cast(Any, self.app)
        patches = list(getattr(app, "patches", ()))
        index = next(
            (
                position
                for position, patch in enumerate(patches)
                if patch_row_target(patch) == target
            ),
            None,
        )
        if index is None:
            return False
        from ...models.group_fold import GroupFoldRegistry
        from ...models.patch_groups import build_patch_tree

        mode = getattr(app, "_patch_grouping_mode", None)
        if mode is None:
            return False
        entries = build_patch_tree(
            patches, mode=mode, fold_registry=GroupFoldRegistry()
        )
        keys = [
            entry.group.group_key
            for entry in entries
            if entry.kind == "group"
            and entry.group is not None
            and index in entry.group.patch_indices
        ]
        registry = getattr(app, "_patch_group_fold_registry", None)
        if registry is None or not keys:
            return False
        changed = bool(registry.expand_keys(keys))
        if changed:
            refresh = getattr(app, "_refresh_display", None)
            if callable(refresh):
                refresh()
        return changed

    def host_reveal_context(self, target: ArtifactEntryTarget) -> Any | None:
        """Return the stack or identity context query for *target*.

        Non-terminal targets show the whole stack through the root of
        their parent chain; terminal (Submitted/Reverted/Archived) targets
        use ``name:``, which lifts the hide toggles through query
        introspection.
        """
        from sase.ace.link_reveal_context import RevealContext
        from sase.ace.query.matchers import get_base_status

        if target.pane_id != "patches" or len(target.parts) < 2:
            return None
        app = cast(Any, self.app)
        patches = list(getattr(app, "_all_patches", ()))
        project, name = target.parts[0], target.parts[1]
        patch = next(
            (
                item
                for item in patches
                if item.project_name == project and item.name == name
            ),
            None,
        )
        if patch is None:
            return None
        by_name: dict[str, Any] = {}
        for item in patches:
            by_name.setdefault(item.name.casefold(), item)
        root = patch.name
        current = patch
        seen = {patch.name.casefold()}
        while current.parent:
            parent = by_name.get(current.parent.casefold())
            if parent is None or parent.name.casefold() in seen:
                break
            seen.add(parent.name.casefold())
            root = parent.name
            current = parent
        if get_base_status(patch.status) in ("Submitted", "Reverted", "Archived"):
            return RevealContext(
                alternatives=(("name", patch.name),),
                label=f"patch {patch.name}",
                member_count=1,
            )
        return RevealContext(
            alternatives=(("ancestor", root),),
            label=f"stack {root}",
            member_count=patch_stack_size(patches, by_name, root),
        )

    def host_query_probe(self, target: ArtifactEntryTarget) -> Any | None:
        """Build a Patch-native one-row matcher for *target*.

        Patches evaluate through their own boolean query engine rather
        than the shared Rust corpus, so the default Rust probe cannot
        answer here. The probe mirrors visible membership exactly,
        including the hide toggles the committed query may lift.
        """
        patch = self.host_query_row_for_target(target)
        if patch is None:
            return None
        app = cast(Any, self.app)
        parse = getattr(app, "_parse_patch_query", None)
        if not callable(parse):
            return None
        return PatchMembershipProbe(patch=patch, app=app, parse=parse)

    def host_limit_query(self) -> str:
        """Return the live or committed Patch query used for ``limit:`` paging."""
        app = cast(Any, self.app)
        display = getattr(app, "_display_patch_query", None)
        return display() if callable(display) else ""

    def apply_host_limit_query(self, query: str, *, grow: bool = False) -> None:
        """Commit a rewritten host-limit query through the existing query seam.

        Patches are already fully loaded into app state, so there is no
        bounded snapshot to grow; ``grow`` exists only to keep this
        signature uniform with the other panes' host-query adapter.
        """
        del grow
        app = cast(Any, self.app)
        commit = getattr(app, "_commit_patch_query", None)
        if callable(commit):
            commit(query, notify=False)

    def apply_entry_jump_hints(
        self,
        hints: Mapping[ArtifactEntryTarget, str],
    ) -> None:
        # Patches paint their own adaptive jump hints through the
        # grouping-aware banner/row jump mode; this pane is never the
        # target of the shared non-PR jump-hint renderer.
        del hints

    def clear_entry_jump_hints(self) -> None:
        pass

    def apply_entry_marks(self, marks: set[ArtifactEntryTarget]) -> None:
        del marks
        app = cast(Any, self.app)
        refresh = getattr(app, "_refresh_display", None)
        if callable(refresh):
            refresh()

    def conditional_footer_entries(self) -> tuple[tuple[str, str], ...]:
        # Patches already drive their full conditional footer directly
        # from ``_apply_detail_panel_update``; this pane never feeds the
        # shared non-PR footer-entries renderer.
        return ()

    def relation_panel_accent(self) -> str:
        """Return the legacy Patch relation header color."""
        return "#87D7FF"

    def relation_entry_facts(self) -> Mapping[ArtifactEntryTarget, RelationEntryFact]:
        """Return Patch row labels, statuses, and effective hidden flags."""
        app = cast(Any, self.app)
        patches = getattr(app, "_all_patches", ())
        hide_reverted = bool(getattr(app, "_patch_relation_hide_reverted", False))
        index = self.relation_index()
        cache_key = (id(patches), id(index), hide_reverted)
        cached_key = getattr(app, "_patch_relation_facts_key", None)
        cached = getattr(app, "_patch_relation_facts", None)
        if cached_key == cache_key and cached is not None:
            return cast(Mapping[ArtifactEntryTarget, RelationEntryFact], cached)
        facts: dict[ArtifactEntryTarget, RelationEntryFact] = {}
        graph_getter = getattr(app, "_get_patch_graph_index", None)
        graph = graph_getter() if callable(graph_getter) else None
        if graph is not None and index is not None:
            for edge in index.edges:
                for target in (edge.source, edge.target):
                    if target.pane_id != "patches" or not target.parts:
                        continue
                    name = target.parts[-1]
                    facts.setdefault(
                        target,
                        RelationEntryFact(
                            label=name,
                            status=graph.get_status(name),
                        ),
                    )
        facts.update(
            {
                patch_row_target(patch): RelationEntryFact(
                    label=patch.name,
                    status=patch.status,
                    hidden=hide_reverted and patch_relation_status_hidden(patch.status),
                )
                for patch in patches
            }
        )
        app._patch_relation_facts_key = cache_key
        app._patch_relation_facts = facts
        return facts

    def reveal_entry_target(
        self,
        target: ArtifactEntryTarget,
        *,
        role: RelationRole,
    ) -> bool:
        """Rewrite the composed query to reveal a filtered relation target."""
        app = cast(Any, self.app)
        return bool(app._change_query_for_navigation(target, role))

    def record_relation_origin(self, origin: ArtifactEntryTarget) -> None:
        del origin
        app = cast(Any, self.app)
        push = getattr(app, "_push_patch_to_history", None)
        if callable(push):
            push()

    def relation_index(self) -> RelationIndex | None:
        """Return the app-owned Patch relation index built on the load path."""
        app = cast(Any, self.app)
        getter = getattr(app, "relation_index", None)
        if callable(getter):
            return getter()
        return None


__all__ = ["ArtifactsPatchesPane"]
