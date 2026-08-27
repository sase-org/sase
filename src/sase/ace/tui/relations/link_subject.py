"""Resolve the selected entity to one canonical link-graph subject ref.

Every ACE tab has its own idea of "the selected row"; this module is the one
place that turns whichever one is active into a single vocabulary the link
graph understands. Pure and Textual-free like :mod:`.artifact_links`, so the
three tab adapters are unit-testable against a small duck-typed stand-in
for the app instead of a live Textual app (``bead:sase-ug.5``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sase.artifact_ref_entries import reference_for_agent_name
from sase.core.artifact_entry_target import ArtifactEntryTarget

from .._artifact_tab_model import EXTERNAL_ACCENT
from .artifact_links import parse_link_ref

# Chops are a virtual link-graph subject kind (no owning Artifacts pane, no
# ref-kind catalog entry): the AXE tab resolves them, but nothing else does.
_CHOP_ACCENT = "#5FD7D7"
_CHOP_ICON = "⚒"
_DEFAULT_ICON = "•"


@dataclass(frozen=True, slots=True)
class LinkSubject:
    """The currently selected entity, as a canonical link-graph endpoint."""

    ref: str
    target: ArtifactEntryTarget | None
    accent: str
    icon: str


def accent_and_icon_for_ref(
    ref_kind: str, target: ArtifactEntryTarget | None
) -> tuple[str, str]:
    """Return the (accent, icon) an entity of *ref_kind* should paint with.

    *target* is preferred when present: it resolves through the live
    Artifacts tab descriptors, which already carry the palette-hash accent a
    document-provider kind (``research``, ...) is assigned at runtime.
    ``chop:`` has no such descriptor since it is virtual, so it is special
    cased directly.
    """

    if ref_kind == "chop":
        return _CHOP_ACCENT, _CHOP_ICON
    if target is not None:
        from ..artifact_tabs import descriptor_for_artifacts_pane_id

        descriptor = descriptor_for_artifacts_pane_id(target.pane_id)
        if descriptor is not None:
            return descriptor.accent, descriptor.icon
    return EXTERNAL_ACCENT, _DEFAULT_ICON


def _ref_for_target(target: ArtifactEntryTarget) -> str | None:
    """Invert :func:`target_for_ref_kind`: a real target back to a ref string."""

    if not target.parts:
        return None
    pane_id = target.pane_id
    payload = str(target.parts[-1])
    if pane_id == "stitches":
        if len(target.parts) < 2:
            return None
        return f"stitch:{target.parts[0]}@{target.parts[1]}"
    if pane_id == "patches":
        return f"patch:{payload}"
    if pane_id == "beads":
        return f"bead:{payload}"
    if pane_id == "files":
        return f"file:{payload}"
    if pane_id == "agents":
        return reference_for_agent_name(payload)
    kind = pane_id.removeprefix("ref:")
    if kind != pane_id and kind:
        return f"{kind}:{payload}"
    return None


def _subject_from_target(target: ArtifactEntryTarget | None) -> LinkSubject | None:
    if target is None:
        return None
    ref = _ref_for_target(target)
    if ref is None:
        return None
    parsed = parse_link_ref(ref)
    ref_kind = parsed[0] if parsed is not None else ""
    accent, icon = accent_and_icon_for_ref(ref_kind, target)
    return LinkSubject(ref=ref, target=target, accent=accent, icon=icon)


def _subject_from_artifacts(app: Any) -> LinkSubject | None:
    pane = app._artifacts_entry_navigator()
    if pane is None:
        return None
    return _subject_from_target(pane.selected_entry_target())


def _subject_from_agents(app: Any) -> LinkSubject | None:
    agent = app._get_selected_agent()
    if agent is None:
        return None
    ref = reference_for_agent_name(agent.name)
    if ref is None:
        return None
    target = ArtifactEntryTarget("agents", (agent.name,))
    accent, icon = accent_and_icon_for_ref("agent", target)
    return LinkSubject(ref=ref, target=target, accent=accent, icon=icon)


def _subject_from_axe(app: Any) -> LinkSubject | None:
    items = getattr(app, "_axe_items", None)
    current_idx = getattr(app, "current_idx", -1)
    if not items or not (0 <= current_idx < len(items)):
        return None
    from ..actions.axe_display._loader_items import axe_item_key

    key = axe_item_key(items[current_idx])
    if key[0] != "chop":
        return None
    lumberjack, chop_name = key[1], key[2]
    snapshots = getattr(app, "_axe_chop_snapshots", {})
    snapshot = snapshots.get((lumberjack, chop_name))
    base = snapshot.base_identity[1] if snapshot is not None else chop_name
    ref = f"chop:{lumberjack}/{base}"
    accent, icon = accent_and_icon_for_ref("chop", None)
    return LinkSubject(ref=ref, target=None, accent=accent, icon=icon)


_ADAPTERS = {
    "artifacts": _subject_from_artifacts,
    "agents": _subject_from_agents,
    "axe": _subject_from_axe,
}


def selected_link_subject(app: Any) -> LinkSubject | None:
    """Return the current tab's selected entity as a link-graph subject.

    ``None`` means the current row cannot be resolved to a ref at all — a
    synthetic banner, a lumberjack or background-command row, an unsupported
    kind — which is the same "nothing to show" state as a resolvable entity
    with zero links; see the rail's invisibility contract.
    """

    adapter = _ADAPTERS.get(str(getattr(app, "current_tab", "")))
    if adapter is None:
        return None
    return adapter(app)


__all__ = [
    "LinkSubject",
    "accent_and_icon_for_ref",
    "selected_link_subject",
]
