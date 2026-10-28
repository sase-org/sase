"""One mixin hosting every Footprint TUI recording seam.

Every hit goes through :func:`sase.footprint._tui.bump`, so the event
loop only ever pays for a dict increment. The daemon flush thread owns
all file I/O. All helpers fail open: recording never changes TUI
behavior.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from sase.footprint import _tui as _counter
from sase.footprint import ids

if TYPE_CHECKING:
    from textual.dom import DOMNode
    from textual.screen import Screen

# Widget class-name fragment -> keymap scope. Checked in order; the first
# case-insensitive substring match wins. Anything unknown is app scope:
# every ``action_*`` method lives on an ``AceApp`` mixin.
_SCOPE_HINTS: tuple[tuple[str, str], ...] = (
    ("statistic", "statistics"),
    ("confighub", "config"),
    ("config_hub", "config"),
    ("gate", "gate"),
    ("machine", "machines"),
    ("memory", "memory"),
    ("snippet", "snippets"),
    ("project", "projects"),
    ("toolrun", "tool_runs"),
    ("tool_run", "tool_runs"),
    ("commandline", "command_line"),
    ("command_line", "command_line"),
)

# Built-in prefix modes recorded through the mode seam. ``saved_query``
# is handled separately (digit slots); ``custom`` collapses to ~custom.
_BUILTIN_MODES: tuple[str, ...] = ("fold", "copy", "leader", "bang", "bead_issue")

# Copy-mode keymap subgroups keyed by where the copy runs.
_COPY_GROUP_FOR_PANE: dict[str, str] = {
    "patches": "patches",
    "stitches": "artifacts_stitches",
    "plans": "artifacts_plans",
    "documents": "artifacts_documents",
    "beads": "artifacts_beads",
}

_CLASS_SCOPE_CACHE: dict[type, str] = {}


def _scope_for(namespace: Any) -> str:
    """Return the keymap scope for a run_action namespace object.

    Only the concrete class name is considered: matching against the full
    MRO would catch mixin names (for example ``AgentDismissMemoryMixin``
    on ``AceApp``) and mis-scope app actions.
    """
    if namespace is None:
        return "app"
    cls = type(namespace)
    cached = _CLASS_SCOPE_CACHE.get(cls)
    if cached is not None:
        return cached
    name = cls.__name__.lower()
    scope = "app"
    for fragment, candidate in _SCOPE_HINTS:
        if fragment in name:
            scope = candidate
            break
    _CLASS_SCOPE_CACHE[cls] = scope
    return scope


def _flatten(keys: Mapping[str, Any], prefix: str, out: dict[str, str]) -> None:
    """Map raw key strings to dotted fields, mirroring the catalog generator."""
    for field, spec in keys.items():
        if isinstance(spec, dict):
            _flatten(spec, f"{prefix}.{field}", out)
        else:
            out[str(spec)] = f"{prefix}.{field}" if prefix else field


class FootprintTuiMixin:
    """Recording seams for :class:`AceApp`. First in the bases order."""

    _footprint_mouse_flag: bool = False
    _footprint_mode_maps_id: int | None = None
    _footprint_mode_maps: dict[str, dict[str, list[str]]] | None = None
    _footprint_tabs_seen: set[str] | None = None

    # -- low-level ------------------------------------------------------
    def _footprint_bump(self, feature_id: str, via: str) -> None:
        try:
            _counter.bump(feature_id, via)
        except Exception:
            pass

    # -- run_action seam --------------------------------------------------
    async def run_action(  # type: ignore[no-untyped-def]
        self,
        action,
        default_namespace=None,
        namespaces=None,
    ) -> bool:
        result = await super().run_action(action, default_namespace, namespaces)  # type: ignore[misc]
        if result:
            try:
                self._footprint_record_action(action, default_namespace)
            except Exception:
                pass
        return result

    def _footprint_record_action(self, action: Any, namespace: Any) -> None:
        if isinstance(action, tuple):
            name = action[1] if len(action) > 1 and isinstance(action[1], str) else ""
        elif isinstance(action, str):
            name = action.split("(", 1)[0].strip()
            if ":" in name:
                name = name.rsplit(":", 1)[-1]
        else:
            return
        if not name:
            return
        scope = _scope_for(namespace if namespace is not None else self)
        feature_id = ids.tui_id(scope, name)
        if feature_id in ids.NAVIGATION_ACTIONS:
            return
        via = "mouse" if self._footprint_mouse_flag else "key"
        self._footprint_mouse_flag = False
        self._footprint_bump(feature_id, via)

    # -- mouse seam ---------------------------------------------------------
    def on_mouse_down(self, event: Any) -> None:
        self._footprint_mouse_flag = True
        return super().on_mouse_down(event)  # type: ignore[misc]

    # -- palette seam target --------------------------------------------------
    def _footprint_record_palette(self, spec_id: str) -> None:
        if not isinstance(spec_id, str) or not spec_id:
            return
        if spec_id.startswith("custom."):
            self._footprint_bump(ids.custom_id("tui"), "palette")
            return
        feature_id = f"tui:{ids.sanitize(spec_id)}"
        if not ids.is_valid_feature_id(feature_id):
            self._footprint_bump(ids.other_id("tui"), "palette")
            return
        if feature_id in ids.NAVIGATION_ACTIONS:
            return
        self._footprint_bump(feature_id, "palette")

    # -- prefix-mode seam ------------------------------------------------------
    def _footprint_mode_maps_current(self) -> dict[str, dict[str, list[str]]]:
        registry = getattr(self, "_keymap_registry", None)
        if registry is None:
            return {}
        if self._footprint_mode_maps is not None and self._footprint_mode_maps_id == id(
            registry
        ):
            return self._footprint_mode_maps
        modes: dict[str, dict[str, list[str]]] = {}
        for short in _BUILTIN_MODES:
            mode_name = f"{short}_mode" if short != "bead_issue" else "bead_issue_mode"
            mode = (getattr(registry, "modes", {}) or {}).get(mode_name)
            keys = getattr(mode, "keys", None)
            if not isinstance(keys, dict):
                continue
            flat: dict[str, str] = {}
            _flatten(keys, short, flat)
            grouped: dict[str, list[str]] = {}
            for raw_key, dotted in flat.items():
                grouped.setdefault(raw_key, []).append(dotted)
            modes[short] = grouped
        self._footprint_mode_maps = modes
        self._footprint_mode_maps_id = id(registry)
        return modes

    def _footprint_record_mode_key(self, mode: str, key: str) -> None:
        if not isinstance(key, str) or key == "escape":
            return
        if mode == "custom":
            self._footprint_bump(ids.custom_id("tui"), "mode")
            return
        if mode == "saved_query":
            if len(key) == 1 and key.isdigit():
                self._footprint_bump(f"tui:saved_query.{key}", "mode")
            return
        if mode not in _BUILTIN_MODES:
            return
        candidates = self._footprint_mode_maps_current().get(mode, {}).get(key)
        if not candidates:
            return
        dotted = self._footprint_disambiguate(mode, key, sorted(candidates))
        self._footprint_bump(f"tui:{dotted}", "mode")

    def _footprint_disambiguate(
        self, mode: str, key: str, candidates: list[str]
    ) -> str:
        del key
        if len(candidates) == 1 or mode != "copy":
            return candidates[0]
        try:
            if getattr(self, "current_tab", None) == "agents":
                for dotted in candidates:
                    if dotted in (
                        "copy.agents.chat",
                        "copy.agents.name",
                    ) or dotted.startswith("copy.agents."):
                        return dotted
            pane = getattr(self, "current_artifacts_pane_key", None)
            want = _COPY_GROUP_FOR_PANE.get(str(pane)) if pane is not None else None
            if want is not None:
                for dotted in candidates:
                    if dotted.startswith(f"copy.{want}."):
                        return dotted
        except Exception:
            pass
        return candidates[0]

    # -- view-entry seams ---------------------------------------------------------
    def _footprint_record_view(self, feature_id: str) -> None:
        if ids.is_valid_feature_id(feature_id):
            self._footprint_bump(feature_id, "key")

    def _footprint_record_tab(self, tab: Any) -> None:
        if getattr(self, "_mounting", False):
            return
        if getattr(self, "_startup_initial_tab", None) is None:
            return
        name = str(tab)
        seen = self._footprint_tabs_seen
        if seen is None:
            seen = set()
            self._footprint_tabs_seen = seen
        if name == str(getattr(self, "_startup_initial_tab", None)) and not seen:
            seen.add(name)
            return
        seen.add(name)
        self._footprint_record_view(ids.tab_view_id(name))

    def _footprint_record_subtab(self, subtab: Any) -> None:
        if getattr(self, "_mounting", False):
            return
        if getattr(self, "_startup_initial_tab", None) is None:
            return
        self._footprint_record_view(ids.tab_view_id(str(subtab)))

    def _footprint_record_admin_tab(self, tab: Any) -> None:
        self._footprint_record_view(ids.admin_view_id(str(tab)))

    def _footprint_record_stats_view(self, view: Any) -> None:
        name = getattr(view, "value", view)
        self._footprint_record_view(ids.stats_view_id(str(name)))

    # -- modal seam ------------------------------------------------------------------
    def push_screen(  # type: ignore[no-untyped-def]
        self,
        screen,
        callback=None,
        wait_for_dismiss=False,
        *,
        mode=None,
    ):
        try:
            from textual.screen import ModalScreen

            if isinstance(screen, ModalScreen):
                self._footprint_record_view(ids.modal_id(type(screen).__name__))
        except Exception:
            pass
        return super().push_screen(  # type: ignore[misc]
            screen,
            callback,
            wait_for_dismiss,
            mode=mode,
        )


__all__ = ["FootprintTuiMixin"]
