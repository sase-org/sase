"""End-to-end coverage for the relation-reveal lens on the Patches pane.

Exercises the real ``_change_query_for_navigation`` rewrite plus
``action_prev_query`` against a combined ``PatchMixin``/``NavigationMixin``
app -- no Textual widgets -- so the reveal exit condition (revealing a
filtered-out ancestor from a composed query, then returning restores that
exact composed query and the original selection) is pinned at the level
that actually moves ``query_string``/``current_idx``.
"""

from __future__ import annotations

from collections import OrderedDict

from sase.ace.query import to_canonical_string
from sase.ace.relation_reveal import is_relation_reveal_active
from sase.ace.testing.fixtures import make_patch
from sase.ace.tui._artifact_tab_contract import compile_builtin_contract
from sase.ace.tui.actions.navigation import NavigationMixin
from sase.ace.tui.actions.patch import PatchMixin
from sase.ace.tui.widgets.artifacts.patch_entry import patch_row_target
from sase.ace.tui.widgets.artifacts.entry_navigation import ArtifactEntryTarget
from sase.core.artifact_relation_layout import EMPTY_RELATION_KEYMAP, RelationRole
from sase.ace.patch import Patch


class _RevealTestApp(PatchMixin, NavigationMixin):
    """Minimal stand-in for AceApp exercising real Patch query rewriting."""

    def __init__(self, patches: list[Patch]) -> None:
        self._all_patches = patches
        self.patches = patches
        self.current_idx = 0
        self.current_tab = "artifacts"
        self.current_artifacts_subtab = "patches"
        self.active_artifacts_contract = compile_builtin_contract(
            "patches", label="Patch", icon="", accent="#87D7FF"
        )
        self.hide_reverted = False
        self.hide_submitted = False
        self.marked_indices: set[int] = set()
        self._hidden_reverted_count = 0
        self._hidden_submitted_count = 0
        self._patches_first_load_done = True
        self._current_patch_group_key = None
        self._query_history: dict = {}
        self._saved_queries: dict = {}
        self._query_selections: dict = {}
        self._relation_reveals: dict = {}
        self._relation_keymap = EMPTY_RELATION_KEYMAP
        self._patch_query_profile = None
        self._patch_query_index = None
        self._patch_query_index_source_list_id = None
        self._patch_query_index_generation = 0
        self._patch_query_result_cache: OrderedDict = OrderedDict()
        self._patch_relation_index = None
        self._patch_relation_index_for_id = None
        self._pr_unmirrored_counts_by_display_name: dict = {}
        self._artifacts_marked_targets: dict[str, set[ArtifactEntryTarget]] = {
            "patches": set()
        }
        self.notifications: list[tuple[str, str]] = []
        self.query_string = "status:ready"
        self.parsed_query = self._parse_patch_query(self.query_string)

    def set_query(self, source: str) -> None:
        self.query_string = source
        self.parsed_query = self._parse_patch_query(source)
        self._load_patches()

    def _load_patches(self) -> None:
        self._apply_patches(self._all_patches)

    def _refresh_display(self) -> None:
        pass

    @property
    def canonical_query_string(self) -> str:
        return to_canonical_string(self.parsed_query)

    def notify(
        self, message: str, *, severity: str = "information", **_: object
    ) -> None:
        self.notifications.append((message, severity))


def _patches() -> list[Patch]:
    return [
        make_patch(name="root", file_path="/tmp/proj/root.sase"),
        make_patch(
            name="root_child", parent="root", file_path="/tmp/proj/root_child.sase"
        ),
        make_patch(name="unrelated", file_path="/tmp/proj/unrelated.sase"),
    ]


def test_reveal_ancestor_then_return_restores_composed_query_and_selection() -> None:
    app = _RevealTestApp(_patches())
    app.set_query("name:root_child")
    assert [p.name for p in app.patches] == ["root_child"]
    app.current_idx = 0
    composed_source = app.query_string
    composed_canonical = app.canonical_query_string

    root = next(p for p in app._all_patches if p.name == "root")
    handled = app._change_query_for_navigation(
        patch_row_target(root), RelationRole.ANCESTOR
    )

    assert handled is True
    assert app.query_string == "ancestor:root"
    assert {p.name for p in app.patches} == {"root", "root_child"}
    assert app.patches[app.current_idx].name == "root"

    reveal = app._relation_reveals.get("patches")
    assert reveal is not None
    assert reveal.relation == "ancestors"
    assert reveal.role is RelationRole.ANCESTOR
    assert reveal.label == "Ancestors"
    assert reveal.origin.source == composed_source
    assert reveal.origin.canonical == composed_canonical
    assert is_relation_reveal_active(
        reveal, pane_id="patches", current_canonical=app.canonical_query_string
    )

    app.action_prev_query()

    assert app.query_string == composed_source
    assert app.canonical_query_string == composed_canonical
    assert [p.name for p in app.patches] == ["root_child"]
    assert app.patches[app.current_idx].name == "root_child"
    # The lens is derived from the live query, not a stored flag: once the
    # query has moved on there is nothing left to explicitly clear.
    assert not is_relation_reveal_active(
        app._relation_reveals.get("patches"),
        pane_id="patches",
        current_canonical=app.canonical_query_string,
    )


def test_reveal_reports_dangling_when_profile_has_no_field_for_role() -> None:
    app = _RevealTestApp(_patches())
    app.set_query("name:root_child")

    target = patch_row_target(app._all_patches[2])  # "unrelated", a LINK-less target
    handled = app._change_query_for_navigation(target, RelationRole.LINK)

    assert handled is False
    assert app.query_string == "name:root_child"
    assert "patches" not in app._relation_reveals


def test_reveal_reports_failure_not_success_when_rewrite_still_misses_target() -> None:
    """A rewrite that lands but doesn't select the target must not report success.

    ``build_relation_reveal_query`` writes a query from the target's *name*
    alone -- it never checks the name exists -- so a rewrite can "succeed"
    (parse, commit, reload) while the target is still nowhere in the
    reloaded list. Before this fix that case still returned ``True``, so the
    follow path recorded a successful reveal for a target it never actually
    selected.
    """
    app = _RevealTestApp(_patches())
    app.set_query("name:root_child")
    composed_source = app.query_string

    ghost = ArtifactEntryTarget("patches", ("demo", "ghost"))
    handled = app._change_query_for_navigation(ghost, RelationRole.ANCESTOR)

    assert handled is False
    assert app.query_string == "ancestor:ghost"
    assert "patches" not in app._relation_reveals
    assert app.notifications == [
        ("ghost is not reachable through ancestor:ghost", "warning")
    ]

    # The rewrite still landed (this fixes false-success reporting, not the
    # rewrite itself) so restoring the prior query still works -- a caller
    # just never gets a reveal lens for a target it never selected.
    app.set_query(composed_source)
    assert [p.name for p in app.patches] == ["root_child"]
