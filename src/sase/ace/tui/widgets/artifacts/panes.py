"""Pane widgets and lazy lifecycle seam for the Artifacts tab."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Static

from sase.ace.query_profile import compiled_profile_for_builtin_pane
from sase.core.artifact_relations import RelationIndex

from ...keymaps import KeymapRegistry, key_display_name, load_keymap_registry
from ..._artifact_tab_model import ArtifactsPaneContract
from ..patch_detail import PatchDetail
from ..patch_info_panel import PatchInfoPanel
from ..patch_list import PatchList
from ..tab_quickstart import TabQuickStart
from .lifecycle import ArtifactsPaneLifecycle
from .entry_navigation import (
    ArtifactEntryNavigator,
    ArtifactEntryTarget,
    LinkRequestState,
)
from .patch_filter_bar import PatchFilterBar
from .patches_filter_session import PatchesFilterSessionMixin
from .patch_entry import patch_row_target
from .relation_panel import (
    RelationEntryFact,
    RelationPanel,
    RelationPanelHostMixin,
    RelationRole,
)
from .shell import build_degraded_card
from .types import ARTIFACTS_ACCENTS, ArtifactsSubTab


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
            member_count=_patch_stack_size(patches, by_name, root),
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
        return _PatchMembershipProbe(patch=patch, app=app, parse=parse)

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
                    hidden=hide_reverted
                    and _patch_relation_status_hidden(patch.status),
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


def _patch_relation_status_hidden(status: str) -> bool:
    return status.startswith("Reverted") or status.startswith("Archived")


def _patch_stack_size(
    patches: list[Any],
    by_name: dict[str, Any],
    root: str,
) -> int | None:
    """Count the stack rooted at *root*: the root plus its descendants."""
    folded = root.casefold()
    count = 0
    for item in patches:
        seen = {item.name.casefold()}
        current = item
        while current.name.casefold() != folded:
            parent_name = getattr(current, "parent", None)
            if not parent_name:
                break
            parent = by_name.get(str(parent_name).casefold())
            if parent is None or parent.name.casefold() in seen:
                break
            seen.add(parent.name.casefold())
            current = parent
        if current.name.casefold() == folded:
            count += 1
    return count or None


class _PatchMembershipProbe:
    """One-row Patch matcher mirroring visible list membership.

    Uses the pane's own boolean query engine (not the shared Rust corpus)
    plus the same hide-toggle lifting the list applies, so Context
    verification and hidden-reason analysis agree with what the user sees.
    """

    def __init__(self, *, patch: Any, app: Any, parse: Any) -> None:
        self._patch = patch
        self._app = app
        self._parse = parse

    def matches(self, query: str) -> bool:
        """Return whether *query* would show this probe's Patch."""
        from sase.ace.query import QueryParseError
        from sase.ace.query.evaluator import evaluate_query
        from sase.ace.query.introspection import (
            query_explicitly_targets_submitted,
            query_explicitly_targets_terminal,
        )
        from sase.ace.query.matchers import get_base_status

        try:
            parsed = self._parse(query)
        except QueryParseError:
            return False
        except Exception:  # noqa: BLE001 - a probe failure is not absence
            return False
        try:
            all_patches = list(getattr(self._app, "_all_patches", ()))
            if not evaluate_query(parsed, self._patch, all_patches):
                return False
        except Exception:  # noqa: BLE001 - treat probe errors as excluding
            return False
        base_status = get_base_status(self._patch.status)
        if (
            bool(getattr(self._app, "hide_reverted", False))
            and base_status in ("Reverted", "Archived")
            and not query_explicitly_targets_terminal(parsed, all_patches)
        ):
            return False
        if (
            bool(getattr(self._app, "hide_submitted", False))
            and base_status == "Submitted"
            and not query_explicitly_targets_submitted(parsed, all_patches)
        ):
            return False
        return True


_PLACEHOLDER_COPY: dict[ArtifactsSubTab, tuple[str, str, str]] = {
    "stitches": (
        "Stitches",
        "A cross-repository timeline with messages, tags, and diffs will live here.",
        "The Stitches pane is scaffolded and will load only when you open it.",
    ),
    "beads": (
        "Beads",
        "Task, epic, and phase bead work items will live here.",
        "The Beads pane will load only when you open it.",
    ),
    "files": (
        "Files",
        "Every indexed artifact file, browsable across agents and projects.",
        "The Files pane loads only when you open it.",
    ),
}


class ArtifactPlaceholderPane(ArtifactsPaneLifecycle, Vertical):
    """Quickstart-style empty state used until a pane's feature phase lands."""

    def __init__(self, subtab: ArtifactsSubTab, **kwargs: Any) -> None:
        if subtab == "patches":
            raise ValueError("the Patches pane is not a placeholder")
        super().__init__(**kwargs)
        self.subtab = subtab
        self.project_scope: str | None = None
        self._project_display_name: str | None = None
        self._registry = load_keymap_registry({})
        self._init_artifacts_lifecycle()

    def compose(self) -> ComposeResult:
        yield Static(self._scope_text(), classes="artifacts-pane-info")
        with VerticalScroll(classes="artifacts-placeholder-scroll"):
            yield Static(
                self._hero_text(),
                classes="artifacts-placeholder-hero",
            )
            card = Static(
                self._card_text(),
                classes="artifacts-placeholder-card",
            )
            card.border_title = "Coming soon"
            yield card
            yield Static(
                self._footer_text(),
                classes="artifacts-placeholder-footer",
            )

    def set_keymap_registry(self, registry: KeymapRegistry) -> None:
        """Use configured scope-picker key text in the empty state."""
        self._registry = registry
        self._refresh_content()

    def set_project_scope(
        self,
        project: str | None,
        *,
        display_name: str | None = None,
    ) -> None:
        """Update the shared project scope chip without rebuilding the pane."""
        self.project_scope = project
        self._project_display_name = display_name
        self._refresh_content()

    def _refresh_content(self) -> None:
        if not self.is_mounted:
            return
        self.query_one(".artifacts-pane-info", Static).update(self._scope_text())
        self.query_one(".artifacts-placeholder-card", Static).update(self._card_text())
        self.query_one(".artifacts-placeholder-footer", Static).update(
            self._footer_text()
        )

    def _scope_label(self) -> str:
        if self.project_scope is not None:
            return self._project_display_name or self.project_scope
        if self.subtab == "stitches":
            return "All projects"
        return "Pick a project"

    def _scope_text(self) -> Text:
        accent = ARTIFACTS_ACCENTS[self.subtab]
        text = Text()
        text.append(f" {self.subtab.title()} ", style=f"bold #1a1a1a on {accent}")
        text.append("  Project scope  ", style="dim")
        text.append(f" {self._scope_label()} ", style=f"bold {accent}")
        text.append("  ·  ", style="dim")
        text.append(
            f"{key_display_name(self._registry.app.pick_artifacts_project)} change",
            style="dim",
        )
        return text

    def _hero_text(self) -> Text:
        title, summary, _footer = _PLACEHOLDER_COPY[self.subtab]
        accent = ARTIFACTS_ACCENTS[self.subtab]
        text = Text(justify="center")
        text.append("*  ", style="bold #FFD700")
        text.append(title, style="bold #FFFFFF")
        text.append("  *\n", style="bold #FFD700")
        text.append(summary, style=f"dim {accent}")
        return text

    def _card_text(self) -> Text:
        accent = ARTIFACTS_ACCENTS[self.subtab]
        text = Text()
        text.append("Lazy by design\n", style=f"bold {accent}")
        text.append(
            "This pane stays mounted so selection and cached state will survive "
            "sub-tab switches. Its data lifecycle starts on first activation and "
            "pauses whenever the pane is hidden."
        )
        return text

    def _footer_text(self) -> Text:
        _title, _summary, footer = _PLACEHOLDER_COPY[self.subtab]
        return Text(footer, style="dim italic", justify="center")

    def entry_targets(self) -> tuple[ArtifactEntryTarget, ...]:
        return ()

    def selected_entry_target(self) -> ArtifactEntryTarget | None:
        return None

    def select_entry_target(self, target: ArtifactEntryTarget) -> bool:
        del target
        return False

    def apply_entry_jump_hints(
        self,
        hints: Mapping[ArtifactEntryTarget, str],
    ) -> None:
        del hints

    def clear_entry_jump_hints(self) -> None:
        pass

    def apply_entry_marks(self, marks: set[ArtifactEntryTarget]) -> None:
        del marks


class ArtifactsDegradedPane(ArtifactsPaneLifecycle, Vertical):
    """Visible failure state for a provider tab that could not be resolved."""

    def __init__(
        self,
        *,
        provider_kind: str,
        provider_label: str,
        error: str,
        error_code: str | None = None,
        error_source: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.provider_kind = provider_kind
        self.provider_label = provider_label
        self.error = error
        self.error_code = error_code
        self.error_source = error_source
        self._init_artifacts_lifecycle()

    def compose(self) -> ComposeResult:
        hero_text, card_text = build_degraded_card(
            provider_kind=self.provider_kind,
            provider_label=self.provider_label,
            error=self.error,
            error_code=self.error_code,
            error_source=self.error_source,
        )
        hero = Static(hero_text, classes="artifacts-degraded-hero")
        card = Static(card_text, classes="artifacts-degraded-card")
        card.border_title = "Provider unavailable"
        yield hero
        yield card


__all__ = [
    "ArtifactPlaceholderPane",
    "ArtifactsDegradedPane",
    "ArtifactsPaneLifecycle",
    "ArtifactsPatchesPane",
]
