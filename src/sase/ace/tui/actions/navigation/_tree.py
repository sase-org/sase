"""Tree navigation mixin for ancestry/child/sibling navigation."""

from __future__ import annotations

from typing import Any, cast

from sase.ace.tui._artifact_tab_model import PaneCapability
from sase.ace.tui.tab_order import ARTIFACTS_TAB
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.artifact_relation_layout import (
    EMPTY_RELATION_KEYMAP,
    RelationKeymap,
    RelationRole,
)

from ._types import NavigationMixinBase


class TreeNavigationMixin(NavigationMixinBase):
    """Mixin providing ancestry/child/sibling tree navigation."""

    def _relation_keymap_or_empty(self) -> RelationKeymap:
        keymap = getattr(self, "_relation_keymap", EMPTY_RELATION_KEYMAP)
        return keymap if isinstance(keymap, RelationKeymap) else EMPTY_RELATION_KEYMAP

    def _relation_contract(self) -> Any | None:
        contract = getattr(self, "active_artifacts_contract", None)
        if contract is not None:
            return contract
        if self.current_tab in {
            "patches",
            "changespecs",  # legacy compatibility alias
        }:
            from sase.ace.tui._artifact_tab_contract import compile_builtin_contract

            return compile_builtin_contract(
                "patches",
                label="Patch",
                icon="",
                accent="",
            )
        return None

    def _relation_navigator(self) -> Any | None:
        getter = getattr(self, "_artifacts_entry_navigator", None)
        if not callable(getter):
            return None
        if self.current_tab in {
            "patches",
            "changespecs",  # legacy compatibility alias
        }:
            return getter("patches")
        if self.current_tab != "artifacts":
            return None
        return getter()

    def _relation_navigation_available(self, role: RelationRole) -> bool:
        contract = self._relation_contract()
        if contract is not None and not contract.has(PaneCapability.RELATIONS):
            return False
        keymap = self._relation_keymap_or_empty()
        if role is RelationRole.ANCESTOR:
            return bool(keymap.ancestors)
        if role is RelationRole.DESCENDANT:
            return bool(keymap.children)
        if role is RelationRole.FAMILY:
            return bool(keymap.siblings)
        return False

    # --- Ancestry Navigation Actions ---

    def action_start_ancestor_mode(self) -> None:
        """Enter ancestor navigation mode (< key pressed)."""
        if not self._relation_navigation_available(RelationRole.ANCESTOR):
            return
        keymap = self._relation_keymap_or_empty()

        # If only one ancestor, navigate directly
        if len(keymap.ancestors) == 1:
            self._navigate_to_relation_target(
                keymap.ancestors[0][1],
                role=RelationRole.ANCESTOR,
            )
        elif len(keymap.ancestors) > 1:
            self._ancestor_mode_active = True

    def action_start_child_mode(self) -> None:
        """Enter child navigation mode (> key pressed)."""
        if not self._relation_navigation_available(RelationRole.DESCENDANT):
            return
        keymap = self._relation_keymap_or_empty()

        # If only one child with key ">" (single leaf child), navigate directly
        if len(keymap.children) == 1 and keymap.children[0][0] == ">":
            self._navigate_to_relation_target(
                keymap.children[0][1],
                role=RelationRole.DESCENDANT,
            )
        else:
            self._child_key_buffer = ""
            self._child_mode_active = True

    def action_start_sibling_mode(self) -> None:
        """Enter sibling/neighbor navigation mode (~ key pressed).

        On the Patch tab this drives Patch sibling navigation; on
        the Agents tab it delegates to dotted-name hood neighbor navigation.
        """
        if self.current_tab == "agents":
            start_agent_neighbors = getattr(
                self, "_start_agent_neighbor_navigation", None
            )
            if callable(start_agent_neighbors):
                start_agent_neighbors()
            return

        if not self._relation_navigation_available(RelationRole.FAMILY):
            return
        keymap = self._relation_keymap_or_empty()

        # If only one family row with key "~", navigate directly
        if len(keymap.siblings) == 1 and keymap.siblings[0][0] == "~":
            self._navigate_to_relation_target(
                keymap.siblings[0][1],
                role=RelationRole.FAMILY,
            )
        else:
            self._sibling_mode_active = True

    def action_toggle_relation_panel(self) -> None:
        """Collapse or expand the Artifacts relation panel."""
        if self.current_tab != ARTIFACTS_TAB:
            return
        self.artifacts_relations_collapsed = not self.artifacts_relations_collapsed
        navigator = getattr(self, "_artifacts_entry_navigator", None)
        pane = navigator() if callable(navigator) else None
        refresh = getattr(pane, "refresh_relation_panel", None)
        if callable(refresh):
            self._relation_keymap = refresh()
        sync = getattr(self, "_sync_active_artifacts_entry_state", None)
        if callable(sync):
            sync()

    def _handle_ancestry_key(self, key: str) -> bool:
        """Handle key in ancestor/child/sibling navigation mode.

        Returns True if the key was handled.
        """
        if self._ancestor_mode_active:
            return self._process_ancestor_key(key)
        elif self._child_mode_active:
            return self._process_child_key(key)
        elif self._sibling_mode_active:
            return self._process_sibling_key(key)
        return False

    def _process_ancestor_key(self, key: str) -> bool:
        """Process key in ancestor mode."""
        self._ancestor_mode_active = False
        keymap = self._relation_keymap_or_empty()

        if key in ("less_than_sign", "<"):
            # << - go to first ancestor (parent)
            if keymap.ancestors:
                self._navigate_to_relation_target(
                    keymap.ancestors[0][1],
                    role=RelationRole.ANCESTOR,
                )
            return True
        elif len(key) == 1 and key.isalpha() and key.islower():
            # <a, <b, etc. - find matching ancestor
            expected_key = f"<{key}"
            target = keymap.target_for(RelationRole.ANCESTOR, expected_key)
            if target is not None:
                self._navigate_to_relation_target(
                    target,
                    role=RelationRole.ANCESTOR,
                )
                return True
        return True  # Consume the key regardless

    def _process_child_key(self, key: str) -> bool:
        """Process key in child mode.

        Handles multi-character sequences like >>, >2, >2a, >2a., etc.
        The buffer accumulates characters until:
        - "." is pressed: navigate to non-leaf node matching buffer
        - Buffer matches a leaf node key: navigate to that node
        - Invalid key: cancel mode
        """
        if key in ("greater_than_sign", ">"):
            # >> - go to first child
            target_key = ">>"
            target = self._relation_keymap_or_empty().target_for(
                RelationRole.DESCENDANT,
                target_key,
            )
            if target is not None:
                self._navigate_to_relation_target(
                    target,
                    role=RelationRole.DESCENDANT,
                )
            self._child_key_buffer = ""
            self._child_mode_active = False
            return True

        if key in ("period", "full_stop", "."):
            # Navigate to non-leaf node
            target_key = ">" + self._child_key_buffer + "."
            target = self._relation_keymap_or_empty().target_for(
                RelationRole.DESCENDANT,
                target_key,
            )
            if target is not None:
                self._navigate_to_relation_target(
                    target,
                    role=RelationRole.DESCENDANT,
                )
            self._child_key_buffer = ""
            self._child_mode_active = False
            return True

        # Validate and accumulate the key
        if self._is_valid_next_child_key(key):
            self._child_key_buffer += key

            # Check if buffer matches a leaf node (no "." suffix)
            target_key = ">" + self._child_key_buffer
            keymap = self._relation_keymap_or_empty()
            target = keymap.target_for(RelationRole.DESCENDANT, target_key)
            if target is not None:
                self._navigate_to_relation_target(
                    target,
                    role=RelationRole.DESCENDANT,
                )
                self._child_key_buffer = ""
                self._child_mode_active = False
                return True

            # Check if buffer could be a prefix for any key
            # If not, cancel the mode
            has_potential_match = any(
                k.startswith(target_key) for k, _ in keymap.children
            )
            if not has_potential_match:
                self._child_key_buffer = ""
                self._child_mode_active = False
                return True

            # Stay in mode, wait for more keys
            return True

        # Invalid key - cancel mode
        self._child_key_buffer = ""
        self._child_mode_active = False
        return True

    def _process_sibling_key(self, key: str) -> bool:
        """Process key in sibling mode.

        Handles sequences like ~~, ~a, ~b, etc.
        """
        self._sibling_mode_active = False
        keymap = self._relation_keymap_or_empty()

        if key in ("tilde", "~"):
            # ~~ - go to first family row
            target = keymap.target_for(RelationRole.FAMILY, "~~")
            if target is not None:
                self._navigate_to_relation_target(
                    target,
                    role=RelationRole.FAMILY,
                )
            return True
        elif len(key) == 1 and key.isalpha() and key.islower():
            # ~a, ~b, etc. - find matching sibling
            expected_key = f"~{key}"
            target = keymap.target_for(RelationRole.FAMILY, expected_key)
            if target is not None:
                self._navigate_to_relation_target(
                    target,
                    role=RelationRole.FAMILY,
                )
            return True

        return True  # Consume the key regardless

    def _is_valid_next_child_key(self, key: str) -> bool:
        """Check if key is valid as the next character in child key sequence.

        Pattern:
        - Empty buffer: accept letter (a-z for >a, >b) OR digit (2-9 for >2, >3)
        - After letter: expect digit 2-9
        - After digit: expect letter a-z
        """
        if len(key) != 1:
            return False

        if not self._child_key_buffer:
            # First character can be letter (for >a, >b) or digit (for >2, >3)
            if key.isalpha() and key.islower():
                return True
            if key.isdigit() and "2" <= key <= "9":
                return True
            return False

        last_char = self._child_key_buffer[-1]
        if last_char.isdigit():
            # After digit, expect letter
            return key.isalpha() and key.islower()
        else:
            # After letter, expect digit
            return key.isdigit() and "2" <= key <= "9"

    def _navigate_to_relation_target(
        self,
        target: ArtifactEntryTarget,
        *,
        role: RelationRole,
    ) -> None:
        pane = self._relation_navigator()
        if pane is None:
            return
        origin = pane.selected_entry_target()
        if origin is not None and origin != target:
            pane.record_relation_origin(origin)
        contract = self._relation_contract()
        pane_id = (
            contract.id
            if contract is not None
            else origin.pane_id
            if origin is not None
            else target.pane_id
        )
        if target.pane_id != pane_id:
            request = getattr(self, "_request_artifacts_entry", None)
            selected = False
            if callable(request):
                selected = bool(request(target))
            if selected:
                return
            pane = self._relation_navigator()
            if pane is None:
                return
            if getattr(pane, "_loading", False) or getattr(
                pane, "_loading_full", False
            ):
                return
        if pane.select_entry_target(target):
            sync = getattr(self, "_sync_active_artifacts_entry_state", None)
            if callable(sync):
                sync()
            return
        if pane.reveal_entry_target(target, role=role):
            return
        label = target.parts[-1] if target.parts else target.pane_id
        notify = getattr(self, "notify", None)
        if callable(notify):
            notify(f"{label} is not in the current results", severity="warning")

    def _navigate_to_patch(
        self,
        target_name: str,
        is_ancestor: bool,
        is_sibling: bool = False,
    ) -> None:
        """Legacy Patch-name shim for relation navigation tests and aliases."""
        role = (
            RelationRole.FAMILY
            if is_sibling
            else RelationRole.ANCESTOR
            if is_ancestor
            else RelationRole.DESCENDANT
        )
        target = self._resolve_patch_relation_target(target_name)
        self._navigate_to_relation_target(target, role=role)

    def _navigate_to_changespec(  # legacy compatibility alias
        self,
        target_name: str,
        is_ancestor: bool,
        is_sibling: bool = False,
    ) -> None:
        """Legacy compatibility alias for old changespec navigation callers."""
        self._navigate_to_patch(target_name, is_ancestor, is_sibling)

    def _resolve_patch_relation_target(self, target_name: str) -> ArtifactEntryTarget:
        name_lower = target_name.lower()
        index_getter = getattr(self, "relation_index", None)
        relation_index = index_getter() if callable(index_getter) else None
        if relation_index is not None:
            for edge in relation_index.edges:
                for target in (edge.source, edge.target):
                    if (
                        target.pane_id == "patches"
                        and target.parts
                        and target.parts[-1].lower() == name_lower
                    ):
                        return target
        from ...widgets.artifacts.patch_entry import patch_row_target

        for patch in getattr(self, "_all_patches", ()):
            if getattr(patch, "name", "").lower() == name_lower:
                return patch_row_target(patch)
        patches = getattr(self, "patches", ())
        project = ""
        if patches and 0 <= getattr(self, "current_idx", 0) < len(patches):
            project = getattr(patches[self.current_idx], "project_name", "")
        return ArtifactEntryTarget(pane_id="patches", parts=(project, target_name))

    def _find_in_current_list(self, name: str) -> int | None:
        """Find a Patch by name in current filtered list."""
        name_lower = name.lower()
        for idx, cs in enumerate(self.patches):
            if cs.name.lower() == name_lower:
                return idx
        return None

    def _change_query_for_navigation(
        self,
        target: ArtifactEntryTarget,
        role: RelationRole,
    ) -> bool:
        """Rewrite the composed Patch query to reveal a filtered-out target.

        The rewrite itself is driven by the active contract's relation
        declarations plus the compiled Patch query profile
        (:func:`~sase.ace.relation_reveal.build_relation_reveal_query`)
        rather than a hard-coded ``ancestor:``/``sibling:`` token, and is
        wrapped in a :class:`~sase.ace.relation_reveal.RelationReveal` lens
        so the shell can advertise a way back through the existing
        `prev_query` (``^``) history stack. Returns whether *target* is
        selected once the rewrite lands; a relation with no matching
        query-profile field, or a rewrite whose result still misses
        *target*, reports ``False`` so the caller can fall back to a
        dangling notice instead of recording a reveal that didn't happen.
        """
        from sase.core.artifact_relation_layout import assign_relation_roles

        from ...widgets.artifacts.patch_entry import patch_row_target
        from ....query import to_canonical_string
        from ....relation_reveal import (
            build_relation_reveal_query,
            make_relation_reveal,
        )

        if not self.patches or not 0 <= self.current_idx < len(self.patches):
            return False
        origin_patch = self.patches[self.current_idx]
        target_name = target.parts[-1] if target.parts else ""
        if not target_name:
            return False

        new_query = build_relation_reveal_query(
            self._patch_profile(),  # type: ignore[attr-defined]
            role,
            origin_name=origin_patch.name,
            target_name=target_name,
        )
        if new_query is None:
            return False

        contract = self._relation_contract()
        relations = contract.relations if contract is not None else ()
        roles = assign_relation_roles(relations)
        decl = next((item for item in relations if roles.get(item.name) is role), None)

        try:
            new_parsed = self._parse_patch_query(new_query)  # type: ignore[attr-defined]
            new_canonical = to_canonical_string(new_parsed)
            current_canonical = self.canonical_query_string  # type: ignore[attr-defined]
            origin_source = self.query_string

            if new_canonical != current_canonical:
                self._record_patch_query_transition(new_canonical)  # type: ignore[attr-defined]

            self.parsed_query = new_parsed
            self.query_string = new_query
            self._load_patches()  # type: ignore[attr-defined]
            self._save_current_query()  # type: ignore[attr-defined]

            # Find and select the target
            target_idx = self._find_in_current_list(target_name)
            if target_idx is None:
                self.notify(  # type: ignore[attr-defined]
                    f"{target_name} is not reachable through {new_query}",
                    severity="warning",
                )
                return False
            self.current_idx = target_idx

            if decl is not None:
                self._relation_reveals["patches"] = make_relation_reveal(
                    pane_id="patches",
                    relation=decl.name,
                    role=role,
                    label=decl.label,
                    origin_source=origin_source,
                    origin_canonical=current_canonical,
                    origin_target=patch_row_target(origin_patch),
                    revealed_canonical=new_canonical,
                )
            return True

        except Exception as e:
            self.notify(f"Navigation error: {e}", severity="error")  # type: ignore[attr-defined]
            return False
