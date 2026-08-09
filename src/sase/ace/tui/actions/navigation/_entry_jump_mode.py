"""Entry-jump mode preparation and hint allocation."""

from __future__ import annotations

from ..agents._panel_fold_intent import effective_panel_collapses
from ._entry_jump_agents import EntryJumpAgentHistoryMixin
from .jump_hints import (
    BannerJumpTarget,
    JumpTarget,
    PanelJumpTarget,
    build_jump_hint_maps,
)


class EntryJumpModeMixin(EntryJumpAgentHistoryMixin):
    """Mixin providing entry-jump mode setup and teardown."""

    def action_jump_to_entry(self) -> None:
        """Enter adaptive jump mode for the current tab's left-panel entries."""
        begin_artifacts = getattr(self, "_begin_non_pr_artifacts_jump_mode", None)
        if callable(begin_artifacts) and begin_artifacts():
            return
        if self.current_tab == "agents" and getattr(
            self, "_panel_fold_hint_mode_active", False
        ):
            self._teardown_panel_fold_hint_mode()  # type: ignore[attr-defined]
        if self.current_tab == "agents":
            self._begin_agents_jump_mode()
            return
        if self.current_tab in {"artifacts", "patches", "changespecs"}:
            self._begin_patch_jump_mode()
            return

        if not self._prepare_entry_jump_index_maps(self._jump_candidate_indices()):
            return
        self._entry_jump_mode_active = True
        self._update_jump_footer()
        self._refresh_current_tab()  # type: ignore[attr-defined]

    def _prepare_entry_jump_index_maps(self, indices: list[int]) -> bool:
        """Allocate generic entry hints without entering/rendering jump mode."""
        if not indices:
            return False
        self._entry_jump_hint_to_index, self._entry_jump_index_to_hint = (
            build_jump_hint_maps(indices)
        )
        self._entry_jump_hint_to_target = dict(self._entry_jump_hint_to_index)
        self._entry_jump_pending_prefix = ""
        return bool(self._entry_jump_hint_to_index)

    def _prepare_patch_jump_maps(self) -> bool:
        """Allocate Patch-row and collapsed-banner hints without rendering them."""
        targets = self._patch_jump_targets()  # type: ignore[attr-defined]
        if not targets:
            return False
        hint_to_target, _ = build_jump_hint_maps(targets)
        if not hint_to_target:
            return False
        self._entry_jump_hint_to_target = dict(hint_to_target)
        self._entry_jump_pending_prefix = ""

        cs_hint_to_idx: dict[str, int] = {}
        cs_idx_to_hint: dict[int, str] = {}
        banner_hint_to_key: dict[str, tuple[str, ...]] = {}
        banner_key_to_hint: dict[tuple[str, ...], str] = {}
        for hint, target in hint_to_target.items():
            kind, payload = target
            if kind in {"patch", "changespec"}:
                assert isinstance(payload, int)
                cs_hint_to_idx[hint] = payload
                cs_idx_to_hint[payload] = hint
            else:
                assert isinstance(payload, tuple)
                banner_hint_to_key[hint] = payload
                banner_key_to_hint[payload] = hint

        self._entry_jump_hint_to_index = cs_hint_to_idx
        self._entry_jump_index_to_hint = cs_idx_to_hint
        self._entry_jump_hint_to_patch_banner = banner_hint_to_key
        self._entry_jump_patch_banner_to_hint = banner_key_to_hint
        self._entry_jump_hint_to_changespec_banner = banner_hint_to_key
        self._entry_jump_changespec_banner_to_hint = banner_key_to_hint
        return True

    def _begin_patch_jump_mode(self) -> None:
        """Allocate hints across visible Patches + collapsed banners (Patches tab, grouped)."""
        if not self._prepare_patch_jump_maps():
            return
        self._entry_jump_mode_active = True
        self._update_jump_footer()
        self._refresh_current_tab()  # type: ignore[attr-defined]

    def _prepare_agents_jump_maps(self) -> bool:
        """Allocate agent-row, banner, and panel-title hints without rendering."""
        guard = getattr(self, "_guard_agent_navigation_for_artifact_file_viewer", None)
        if callable(guard) and guard():
            return False
        targets = self._jump_candidate_targets()
        if not targets:
            return False
        hint_to_target, _ = build_jump_hint_maps(targets)
        if not hint_to_target:
            return False
        self._entry_jump_hint_to_target = dict(hint_to_target)
        self._entry_jump_pending_prefix = ""

        agent_hint_to_idx: dict[str, int] = {}
        agent_idx_to_hint: dict[int, str] = {}
        banner_hint_to_target: dict[str, BannerJumpTarget] = {}
        banner_to_hint: dict[BannerJumpTarget, str] = {}
        panel_hint_to_target: dict[str, PanelJumpTarget] = {}
        panel_to_hint: dict[PanelJumpTarget, str] = {}
        for hint, target in hint_to_target.items():
            if target[0] == "agent":
                agent_hint_to_idx[hint] = target[1]
                agent_idx_to_hint[target[1]] = hint
            elif target[0] == "banner":
                banner_hint_to_target[hint] = target
                banner_to_hint[target] = hint
            else:
                panel_hint_to_target[hint] = target
                panel_to_hint[target] = hint

        self._entry_jump_hint_to_index = agent_hint_to_idx
        self._entry_jump_index_to_hint = agent_idx_to_hint
        self._entry_jump_hint_to_banner = banner_hint_to_target
        self._entry_jump_banner_to_hint = banner_to_hint
        self._entry_jump_hint_to_panel = panel_hint_to_target
        self._entry_jump_panel_to_hint = panel_to_hint
        return True

    def _begin_agents_jump_mode(self) -> None:
        """Allocate hints across visible agents, banners, and panel headers."""
        if not self._prepare_agents_jump_maps():
            return
        self._entry_jump_mode_active = True
        self._update_jump_footer()
        self._refresh_agents_jump_hint_display()

    def _refresh_agents_jump_hint_display(self) -> None:
        """Refresh jump-hint overlays without forcing a full display rebuild."""
        panel_group = getattr(self, "_panel_group", None)
        refresh_affected = getattr(self, "_refresh_affected_panel_widgets", None)
        if (
            panel_group is not None
            and callable(refresh_affected)
            and hasattr(self, "query_one")
        ):
            keys = set(getattr(panel_group, "panel_keys", []))
            if keys and refresh_affected(keys):
                record_patch = getattr(self, "_record_display_patch_trace", None)
                if callable(record_patch):
                    record_patch(display_cost="display_panel_rebuild", count=len(keys))
                return
        self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]

    def _jump_candidate_indices(self) -> list[int]:
        """Return target indices for jump mode in visual order (Patches / AXE only)."""
        if self.current_tab in {"artifacts", "patches", "changespecs"}:
            patches = getattr(self, "patches", getattr(self, "changespecs", []))
            return list(range(len(patches)))
        if self.current_tab == "agents":
            # Kept for backward compatibility with tests / callers that
            # only need the agent indices (no banner targets).
            return [t[1] for t in self._jump_candidate_targets() if t[0] == "agent"]
        return list(range(len(self._axe_items)))  # type: ignore[attr-defined]

    def _jump_candidate_targets(self) -> list[JumpTarget]:
        """Return jump targets for the agents tab in render order.

        Walks each tribe panel's grouping tree (mirroring
        :func:`_refresh_panel_widgets`) so hint characters march down the
        screen in the same order they're rendered. Every split-panel title
        contributes a ``("panel", panel_key)`` target; collapsed panels skip
        their hidden tree, while expanded panels continue with their rows.
        collapsed in-panel banners contribute panel-scoped banner targets.
        """
        from ...models.agent_groups import GroupingMode, build_agent_tree
        from ..agents._fold_scope import panel_fold_registry
        from ..agents._navigation_order import rendered_panel_slice

        mode: GroupingMode = getattr(self, "_grouping_mode", GroupingMode.STANDARD)
        panel_group = getattr(self, "_panel_group", None)
        panel_keys = panel_group.panel_keys if panel_group is not None else [None]
        collapsed_keys = effective_panel_collapses(self, panel_keys)
        split_panels = not getattr(self, "_agent_panels_grouped", False)
        targets: list[JumpTarget] = []
        for panel_idx, key in enumerate(panel_keys):
            if split_panels:
                targets.append(("panel", key))
            if key in collapsed_keys:
                continue
            registry = panel_fold_registry(self, key)
            global_indices, panel_agents = rendered_panel_slice(self, key)
            tree = build_agent_tree(panel_agents, fold_registry=registry, mode=mode)
            for entry in tree:
                if entry.kind == "group" and entry.group is not None:
                    if entry.group.is_collapsed:
                        targets.append(("banner", panel_idx, entry.group.group_key))
                elif entry.kind == "agent" and entry.agent_idx is not None:
                    targets.append(("agent", global_indices[entry.agent_idx]))
        return targets

    def _exit_entry_jump_mode(self) -> None:
        """Clear jump mode state and remove hint overlays."""
        if getattr(self, "_artifacts_jump_mode_subtab", None) is not None:
            cancel_artifacts = getattr(self, "_cancel_non_pr_artifacts_jump_mode", None)
            if callable(cancel_artifacts):
                cancel_artifacts()
                return
        self._entry_jump_mode_active = False
        self._entry_jump_hint_to_target = {}
        self._entry_jump_pending_prefix = ""
        self._entry_jump_hint_to_index = {}
        self._entry_jump_index_to_hint = {}
        self._entry_jump_hint_to_banner = {}
        self._entry_jump_banner_to_hint = {}
        self._entry_jump_hint_to_panel = {}
        self._entry_jump_panel_to_hint = {}
        self._entry_jump_hint_to_patch_banner = {}
        self._entry_jump_patch_banner_to_hint = {}
        self._entry_jump_hint_to_changespec_banner = {}
        self._entry_jump_changespec_banner_to_hint = {}
        if self.current_tab == "agents":
            self._refresh_agents_jump_hint_display()
        else:
            self._refresh_current_tab()  # type: ignore[attr-defined]

    def _update_jump_footer(self) -> None:
        """Update the footer to show jump mode bindings."""
        from ...widgets import KeybindingFooter

        try:
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
            artifacts_has_back = getattr(self, "_artifacts_jump_has_back", None)
            if (
                callable(artifacts_has_back)
                and getattr(self, "_artifacts_jump_mode_subtab", None) is not None
            ):
                has_back = artifacts_has_back()
            elif self.current_tab == "agents":
                has_back = bool(self._entry_jump_agents_anchor_stack)
            else:
                has_back = self._entry_jump_index_stack_has_current_tab_history()
            footer.update_jump_bindings(has_back=has_back)
        except Exception:
            pass
