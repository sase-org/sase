"""Hint-selected folding for every visible Agents-tab fold owner."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from ....hints import parse_numeric_hint_selection
from ._panel_fold_intent import (
    effective_panel_collapses,
    panel_is_collapsed,
    set_panel_fold_intent,
)

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_group_fold import AgentGroupFoldRegistry, GroupKey
    from ...models.agent_panels import AgentPanelGroup, PanelKey
    from ...models.fold_state import FoldStateManager
    from ..navigation.jump_hints import BannerJumpTarget, PanelJumpTarget

type PanelFoldHintTarget = tuple[Literal["panel"], "PanelKey"]
type GroupFoldHintTarget = tuple[Literal["group"], "PanelKey", "GroupKey"]
type AgentFoldHintTarget = tuple[Literal["agent"], "PanelKey", int, str]
type FoldHintTarget = PanelFoldHintTarget | GroupFoldHintTarget | AgentFoldHintTarget


class AgentPanelHintFoldingMixin:
    """Select and atomically toggle visible fold owners by numeric hints."""

    current_tab: str
    current_idx: int
    current_attempt_number: int | None
    _agents: list[Agent]
    _fold_counts: dict[str, tuple[int, int]]
    _fold_manager: FoldStateManager
    _group_fold_registry: AgentGroupFoldRegistry
    _panel_group: AgentPanelGroup
    _agent_panels_grouped: bool
    _collapsed_panel_keys: set[PanelKey]
    _expanded_panel_keys: set[PanelKey]
    _current_group_key: tuple[str, ...] | None
    _hint_mode_active: bool
    _hint_mode_hints_for: str | None
    _panel_fold_hint_mode_active: bool
    _panel_fold_hint_snapshot: tuple[FoldHintTarget, ...]
    _panel_fold_hint_to_target: dict[int, FoldHintTarget]
    _panel_fold_target_to_hint: dict[FoldHintTarget, int]

    def action_toggle_selected_agent_panels(self) -> None:
        """Open the numeric selector for one atomic mixed-fold toggle."""
        if self.current_tab != "agents":
            return
        if self._refocus_existing_hint_bar():  # type: ignore[attr-defined]
            return

        targets = self._enumerate_panel_fold_hint_targets()
        if not targets:
            self.notify(  # type: ignore[attr-defined]
                "No visible folds to select", severity="warning"
            )
            return

        # A title or row must never carry both the apostrophe jump namespace
        # and the numeric fold-selection namespace.
        if getattr(self, "_entry_jump_mode_active", False):
            self._exit_entry_jump_mode()  # type: ignore[attr-defined]

        self._panel_fold_hint_snapshot = targets
        self._panel_fold_hint_to_target = dict(enumerate(targets, start=1))
        self._panel_fold_target_to_hint = {
            target: hint for hint, target in self._panel_fold_hint_to_target.items()
        }
        self._panel_fold_hint_mode_active = True
        self._hint_mode_active = True
        self._hint_mode_hints_for = "folds"

        from ...widgets import HintInputBar

        try:
            detail_container = self.query_one("#agent-detail-container")  # type: ignore[attr-defined]
            if not bool(getattr(detail_container, "is_attached", True)):
                raise RuntimeError("agent detail container is detached")
            detail_container.mount(HintInputBar(mode="panels", id="hint-input-bar"))
        except Exception:
            self._teardown_panel_fold_hint_mode(refresh_titles=False)
            self.notify("Fold selector is unavailable", severity="warning")  # type: ignore[attr-defined]
            return

        self._refresh_panel_fold_hint_display()
        refresh_footer = getattr(self, "_refresh_agent_footer_bindings_only", None)
        if callable(refresh_footer):
            refresh_footer()

    def _enumerate_panel_fold_hint_targets(self) -> tuple[FoldHintTarget, ...]:
        """Return every visible fold owner in panel-and-row render order."""
        from ...models._agent_tree import agent_fold_key
        from ...models.agent_groups import GroupingMode, build_agent_tree
        from ._fold_scope import panel_fold_registry
        from ._navigation_order import rendered_panel_slice

        from ...models.agent_panels import AgentPanelGroup

        panel_group = getattr(self, "_panel_group", None)
        focused_key = getattr(panel_group, "focused_key", None)
        live_panel_group = AgentPanelGroup.from_agents(
            self._agents,
            focused_key,
            merge_tribe_panels=bool(getattr(self, "_agent_panels_grouped", False)),
            collapsed_panel_keys=effective_panel_collapses(self),
        )
        panel_keys = tuple(live_panel_group.panel_keys)
        if not panel_keys:
            return ()

        merged = bool(getattr(self, "_agent_panels_grouped", False))
        collapsed_keys = effective_panel_collapses(self, panel_keys)
        fold_counts = getattr(self, "_fold_counts", {})
        mode: GroupingMode = getattr(self, "_grouping_mode", GroupingMode.STANDARD)
        targets: list[FoldHintTarget] = []
        seen_actions: set[tuple[object, ...]] = set()

        for panel_key in panel_keys:
            panel_collapsed = panel_key in collapsed_keys
            # Every split tribe panel is a real fold owner, even when it is
            # the only panel. The merged ``All agents`` surface is not one.
            if not merged:
                target: FoldHintTarget = ("panel", panel_key)
                targets.append(target)
                seen_actions.add(("panel", panel_key))
            if panel_collapsed:
                continue

            registry = panel_fold_registry(self, panel_key)
            global_indices, panel_agents = rendered_panel_slice(self, panel_key)
            tree = build_agent_tree(panel_agents, fold_registry=registry, mode=mode)
            for entry in tree:
                if entry.kind == "group" and entry.group is not None:
                    action = ("group", panel_key, entry.group.group_key)
                    if action in seen_actions:
                        continue
                    seen_actions.add(action)
                    targets.append(("group", panel_key, entry.group.group_key))
                    continue
                if entry.kind != "agent" or entry.agent_idx is None:
                    continue
                local_idx = entry.agent_idx
                if not (0 <= local_idx < len(panel_agents)):
                    continue
                owner = panel_agents[local_idx]
                # Workflow step rows are controlled by their parent's fold.
                # Family/clan member rows may still own a distinct nested fold.
                if owner.is_workflow_step_child:
                    continue
                fold_key = agent_fold_key(owner)
                if fold_key is None or (
                    not owner.is_clan_container and fold_key not in fold_counts
                ):
                    continue
                agent_action = ("agent-fold", fold_key)
                if agent_action in seen_actions:
                    continue
                seen_actions.add(agent_action)
                targets.append(
                    ("agent", panel_key, global_indices[local_idx], fold_key)
                )

        return tuple(targets)

    def _panel_fold_hint_display_maps(
        self,
    ) -> tuple[
        dict[int, str],
        dict[BannerJumpTarget, str],
        dict[PanelJumpTarget, str],
    ]:
        """Project numeric fold targets onto the existing hint render channels."""
        panel_indices = {
            key: idx
            for idx, key in enumerate(getattr(self._panel_group, "panel_keys", ()))
        }
        agent_hints: dict[int, str] = {}
        banner_hints: dict[BannerJumpTarget, str] = {}
        panel_hints: dict[PanelJumpTarget, str] = {}
        for target, hint in getattr(self, "_panel_fold_target_to_hint", {}).items():
            rendered_hint = str(hint)
            if target[0] == "panel":
                panel_hints[("panel", target[1])] = rendered_hint
            elif target[0] == "group":
                panel_idx = panel_indices.get(target[1])
                if panel_idx is not None:
                    banner_hints[("banner", panel_idx, target[2])] = rendered_hint
            else:
                agent_hints[target[2]] = rendered_hint
        return agent_hints, banner_hints, panel_hints

    def _refresh_panel_fold_hint_display(self) -> None:
        """Repaint fold chips through the selective panel-widget path."""
        panel_group = getattr(self, "_panel_group", None)
        refresh_affected = getattr(self, "_refresh_affected_panel_widgets", None)
        if (
            panel_group is not None
            and callable(refresh_affected)
            and hasattr(self, "query_one")
        ):
            keys = set(getattr(panel_group, "panel_keys", ()))
            if keys and refresh_affected(keys):
                return
        self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]

    def _teardown_panel_fold_hint_mode(self, *, refresh_titles: bool = True) -> None:
        """Clear fold-selection state before removing transient widgets."""
        if not getattr(self, "_panel_fold_hint_mode_active", False):
            return

        self._panel_fold_hint_mode_active = False
        self._panel_fold_hint_snapshot = ()
        self._panel_fold_hint_to_target = {}
        self._panel_fold_target_to_hint = {}
        self._hint_mode_active = False
        self._hint_mode_hints_for = None

        from ...widgets import HintInputBar

        try:
            hint_bar = self.query_one("#hint-input-bar", HintInputBar)  # type: ignore[attr-defined]
            hint_bar.remove()
        except Exception:
            pass

        if refresh_titles and self.current_tab == "agents":
            self._refresh_panel_fold_hint_display()

    def _process_panel_fold_hint_input(self, user_input: str) -> None:
        """Validate a mixed selection and apply one coalesced fold transition."""
        mappings = dict(getattr(self, "_panel_fold_hint_to_target", {}))
        parsed = parse_numeric_hint_selection(user_input, mappings)
        if not user_input.strip() or not parsed.numbers:
            if parsed.malformed or parsed.unavailable:
                self._notify_invalid_panel_hints(parsed.malformed, parsed.unavailable)
            else:
                self.notify(  # type: ignore[attr-defined]
                    "Enter one or more fold hints", severity="warning"
                )
            return
        if parsed.malformed or parsed.unavailable:
            self._notify_invalid_panel_hints(parsed.malformed, parsed.unavailable)
            return

        snapshot = tuple(getattr(self, "_panel_fold_hint_snapshot", ()))
        live_targets = self._enumerate_panel_fold_hint_targets()
        if snapshot != live_targets or any(
            mappings.get(hint) not in live_targets for hint in parsed.numbers
        ):
            self._teardown_panel_fold_hint_mode()
            self.notify(  # type: ignore[attr-defined]
                "Visible folds changed; retry fold selection", severity="warning"
            )
            return

        from ...models.fold_state import FoldLevel
        from ._fold_scope import panel_fold_registry
        from ._navigation_order import rendered_panel_slice

        selected_targets = [mappings[hint] for hint in parsed.numbers]
        focused_key = self._panel_group.focused_key
        expanded = 0
        collapsed = 0
        group_changed = False
        agent_fold_changed = False
        focused_panel_toggled = False

        for target in selected_targets:
            if target[0] == "panel":
                panel_key = target[1]
                if panel_is_collapsed(self, panel_key):
                    set_panel_fold_intent(self, panel_key, collapsed=False)
                    expanded += 1
                    new_collapsed = False
                else:
                    set_panel_fold_intent(self, panel_key, collapsed=True)
                    collapsed += 1
                    new_collapsed = True
                focused_panel_toggled |= panel_key == focused_key
                self._persist_panel_fold_change(  # type: ignore[attr-defined]
                    panel_key, collapsed=new_collapsed
                )
                continue

            if target[0] == "group":
                panel_key, group_key = target[1], target[2]
                registry = panel_fold_registry(self, panel_key)
                if registry.is_collapsed(group_key):
                    changed = registry.expand(group_key)
                    expanded += int(changed)
                    new_collapsed = False
                else:
                    changed = registry.collapse(group_key)
                    collapsed += int(changed)
                    new_collapsed = True
                if changed:
                    group_changed = True
                    self._persist_group_fold_change(  # type: ignore[attr-defined]
                        group_key,
                        collapsed=new_collapsed,
                        panel_key=panel_key,
                    )
                continue

            fold_key = target[3]
            if self._fold_manager.get(fold_key) == FoldLevel.COLLAPSED:
                changed = self._fold_manager.expand(fold_key)
                expanded += int(changed)
            else:
                changed = False
                while self._fold_manager.get(fold_key) != FoldLevel.COLLAPSED:
                    if not self._fold_manager.collapse(fold_key):
                        break
                    changed = True
                collapsed += int(changed)
            agent_fold_changed |= changed

        if focused_panel_toggled:
            self.current_attempt_number = None
            self._current_group_key = None
            focused_now_collapsed = panel_is_collapsed(self, focused_key)
            self._expanded_panel_focus = False
            if focused_now_collapsed:
                global_indices, _panel_agents = rendered_panel_slice(self, focused_key)
                if global_indices:
                    self.current_idx = global_indices[0]

        if group_changed and not panel_is_collapsed(self, focused_key):
            snap_group_focus = getattr(
                self, "_snap_focus_after_group_fold_change", None
            )
            if callable(snap_group_focus):
                snap_group_focus()

        # Clear chips before the one list repaint that applies all mutations.
        self._teardown_panel_fold_hint_mode(refresh_titles=False)
        self._invalidate_agent_panel_cache()  # type: ignore[attr-defined]
        if agent_fold_changed and callable(getattr(self, "_refilter_agents", None)):
            self._refilter_agents(refresh_content_index=False)  # type: ignore[attr-defined]
        else:
            self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]

        parts: list[str] = []
        if expanded:
            parts.append(f"{expanded} expanded")
        if collapsed:
            parts.append(f"{collapsed} collapsed")
        summary = ", ".join(parts) if parts else "no changes"
        self.notify(f"Folds toggled: {summary}", timeout=1.5)  # type: ignore[attr-defined]

    def _notify_invalid_panel_hints(
        self,
        malformed: tuple[str, ...],
        unavailable: tuple[int, ...],
    ) -> None:
        """Explain a rejected fold selection while leaving the bar mounted."""
        details: list[str] = []
        if malformed:
            details.append(f"malformed: {', '.join(malformed)}")
        if unavailable:
            details.append(
                f"unavailable: {', '.join(str(number) for number in unavailable)}"
            )
        self.notify(  # type: ignore[attr-defined]
            f"Invalid fold selection ({'; '.join(details)})",
            severity="warning",
        )


__all__ = ["AgentPanelHintFoldingMixin", "FoldHintTarget"]
