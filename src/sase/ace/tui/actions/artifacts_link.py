"""Typed artifact-link authoring actions for Artifacts panes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from sase.ace.tui.actions.clipboard._artifact_reference_resolution import (
    reference_items_for_targets,
    resolve_artifact_selection,
)
from sase.ace.tui.actions.clipboard._representations import (
    ArtifactReferenceItem,
    ArtifactReferenceSelection,
    ResolvedArtifactItem,
)
from sase.ace.tui.modals.artifact_link_modal import (
    ArtifactLinkModal,
    ArtifactLinkRelationChoice,
    ArtifactLinkResult,
)
from sase.ace.tui.tab_order import ARTIFACTS_TAB
from sase.ace.tui.widgets.artifacts import ArtifactEntryTarget
from sase.sdd.artifact_link_store import assembled_artifact_relations


@dataclass(frozen=True, slots=True)
class _ArtifactLinkDraft:
    subtab: str
    source: ArtifactReferenceItem
    target: ArtifactReferenceItem


class ArtifactsLinkActionsMixin:
    """Create typed artifact links from the active Artifacts pane."""

    current_tab: Any

    def action_artifacts_link_marked(self) -> None:
        """Link the one marked artifact to the selected artifact."""

        draft = self._artifact_link_draft_from_active_pane()
        if draft is None:
            return
        relations = _writable_artifact_relations()
        if not relations:
            self.notify(  # type: ignore[attr-defined]
                "No writable artifact link relations",
                severity="warning",
            )
            return

        def _on_submit(result: ArtifactLinkResult | None) -> None:
            if result is None:
                return
            self._submit_artifact_link_draft(draft, result)

        self.push_screen(  # type: ignore[attr-defined]
            ArtifactLinkModal(
                source_label=draft.source.label,
                target_label=draft.target.label,
                relations=relations,
            ),
            _on_submit,
        )

    def _artifact_link_draft_from_active_pane(self) -> _ArtifactLinkDraft | None:
        if self.current_tab != ARTIFACTS_TAB:
            return None
        pane_key = str(getattr(self, "current_artifacts_pane_key", "patches"))
        if pane_key == "patches":
            self.notify(  # type: ignore[attr-defined]
                "Artifact link authoring is available on non-Patch artifact panes",
                severity="warning",
            )
            return None
        pane = self._artifacts_entry_navigator()  # type: ignore[attr-defined]
        current = pane.selected_entry_target() if pane is not None else None
        if pane is None or current is None:
            self.notify(  # type: ignore[attr-defined]
                "No artifact entry selected",
                severity="warning",
            )
            return None
        marks = set(self._active_artifacts_marks())  # type: ignore[attr-defined]
        if len(marks) != 1:
            self.notify(  # type: ignore[attr-defined]
                "Mark exactly one artifact to link to the current row",
                severity="warning",
            )
            return None
        source = next(iter(marks))
        if source == current:
            self.notify(  # type: ignore[attr-defined]
                "Cannot link an artifact to itself",
                severity="warning",
            )
            return None
        items = reference_items_for_targets(
            pane_key,
            pane,
            (source, current),
        )
        by_target = {item.target: item for item in items}
        source_item = by_target.get(source)
        target_item = by_target.get(current)
        if source_item is None or target_item is None:
            self.notify(  # type: ignore[attr-defined]
                "Selected artifacts do not both have canonical references",
                severity="warning",
            )
            return None
        return _ArtifactLinkDraft(
            subtab=pane_key,
            source=source_item,
            target=target_item,
        )

    def _submit_artifact_link_draft(
        self,
        draft: _ArtifactLinkDraft,
        result: ArtifactLinkResult,
    ) -> None:
        async def _runner() -> None:
            try:
                source, target = await asyncio.to_thread(
                    _resolve_link_endpoints,
                    draft,
                )
                outcome = await asyncio.to_thread(
                    _add_artifact_link,
                    source.reference,
                    result.relation,
                    target.reference,
                    result.reason,
                )
            except Exception as exc:  # noqa: BLE001 - surfaced as a TUI notification
                self.notify(str(exc), severity="error")  # type: ignore[attr-defined]
                return
            kind = str(outcome.get("kind") or "unchanged")
            self.notify(  # type: ignore[attr-defined]
                f"{kind} {result.relation} @{source.reference} -> @{target.reference}"
            )
            refresh = getattr(self, "_request_active_artifacts_refresh", None)
            if callable(refresh):
                refresh()
            refresh_links = getattr(self, "_schedule_link_index_refresh", None)
            if callable(refresh_links):
                refresh_links(source="artifact_link_write")

        from ..util.pump_tasks import spawn_pump_free_task

        task = spawn_pump_free_task(
            self,
            _runner(),
            name="sase-artifacts-link-marked",
            registry_attr="_pump_free_async_tasks",
        )
        if task is None:
            self.notify(  # type: ignore[attr-defined]
                "Unable to start artifact link write",
                severity="error",
            )


def _writable_artifact_relations() -> tuple[ArtifactLinkRelationChoice, ...]:
    choices: list[ArtifactLinkRelationChoice] = []
    for relation in assembled_artifact_relations():
        if str(relation.get("written_by") or "") != "cli":
            continue
        slug = str(relation.get("slug") or "").strip()
        if not slug:
            continue
        choices.append(ArtifactLinkRelationChoice(slug=slug, label=slug))
    return tuple(choices)


def _resolve_link_endpoints(
    draft: _ArtifactLinkDraft,
) -> tuple[ResolvedArtifactItem, ResolvedArtifactItem]:
    selection = ArtifactReferenceSelection(
        subtab=draft.subtab,
        items=(draft.source, draft.target),
        marked=True,
        prompt_project=None,
        prompt_display_name=None,
        prompt_project_file=None,
    )
    resolved = resolve_artifact_selection(selection, include_metadata=False)
    by_target = {item.item.target: item for item in resolved.items}
    source = by_target.get(draft.source.target)
    target = by_target.get(draft.target.target)
    if source is None or target is None:
        detail = "; ".join(resolved.failures) if resolved.failures else ""
        suffix = f": {detail}" if detail else ""
        raise ValueError(f"selected artifacts do not both have references{suffix}")
    return source, target


def _add_artifact_link(
    source_ref: str,
    relation: str,
    target_ref: str,
    reason: str,
) -> dict[str, Any]:
    from sase.artifact_cli.link_ops import add_artifact_link

    return add_artifact_link(
        source_ref=source_ref,
        relation=relation,
        target_ref=target_ref,
        why=reason,
    )


__all__ = ["ArtifactsLinkActionsMixin"]
