"""Shared section-view base for prompt and deck Main views."""

from __future__ import annotations

from typing import Any, Protocol

from textual import events
from textual.containers import ScrollableContainer
from textual.geometry import Size
from textual.timer import Timer
from textual.widgets import Static

from ...models.agent import Agent  # noqa: F401  (type-checking aid)
from ._section_navigation import (
    PromptPanelSectionAnchor,
    PromptPanelSectionRole,
    PromptPanelSectionTarget,
    PromptPanelSectionTargetKind,
    SectionTrackingVisual,
)


class _SectionLayoutPublisher(Protocol):
    """Minimal surface SectionTrackingVisual needs from its owner."""

    def _publish_section_layout(
        self,
        *,
        generation: int,
        width: int,
        anchors: tuple[PromptPanelSectionAnchor, ...],
    ) -> None: ...


class SectionViewMixin(Static):
    """View-side section, pin and layout behavior shared by prompt views."""

    _slow_tool_render_timer: Timer | None = None
    _slow_tool_tick_agent: Any | None = None
    _section_generation: int = 0
    _section_anchor_generation: int = -1
    _section_anchor_width: int = -1
    _section_anchors: tuple[PromptPanelSectionAnchor, ...] = ()
    _active_section_identity: str | None = None
    _pending_section_direction: int | None = None
    _section_document_identity: object
    _section_real_content_height: int = 0
    _section_layout_reserve: int = 0
    _section_layout_reserve_enabled: bool = False
    _section_tracking_visual: SectionTrackingVisual | None = None
    _section_tracking_visual_generation: int = -1
    _section_content_digest: str | None = None
    _preserve_missing_section_next_update: bool = False
    _preserve_missing_section_generation: int = -1
    _pinned_to_bottom: bool = False
    _bottom_pin_reapply_scheduled: bool = False
    _bottom_pin_last_y: int = -1

    def _section_view_features_enabled(self) -> bool:
        """Whether id-gated view features apply to this widget."""
        return True

    def prepare_section_document(self, identity: object) -> None:
        """Set the logical metadata-document identity for cursor reconciliation."""
        previous = getattr(self, "_section_document_identity", _UNSET)
        if previous != identity:
            self._active_section_identity = None
            self._pending_section_direction = None
            self._section_layout_reserve_enabled = False
            self.release_bottom_pin()
        self._section_document_identity = identity

    def reset_section_document(self) -> None:
        """Reset section state for an empty metadata panel."""
        self.prepare_section_document((_EMPTY_DOCUMENT, id(self)))

    def preserve_missing_section_on_next_update(self) -> None:
        """Keep the cursor through one deliberately incomplete cheap paint."""
        self._preserve_missing_section_next_update = True

    def _apply_section_content(
        self, content: Any, digest: str | None, *, layout: bool = True
    ) -> bool:
        """Apply pre-flattened content with digest-skip bookkeeping."""
        previous = getattr(self, "_section_content_digest", None)
        if (
            digest is not None
            and digest == previous
            and getattr(self, "_section_generation", 0) > 0
        ):
            self._preserve_missing_section_next_update = False
            return False
        self._section_content_digest = digest
        self._section_generation = getattr(self, "_section_generation", 0) + 1
        self._preserve_missing_section_generation = (
            self._section_generation
            if self._preserve_missing_section_next_update
            else -1
        )
        self._preserve_missing_section_next_update = False
        self._section_anchor_generation = -1
        self._section_anchor_width = -1
        self._section_anchors = ()
        Static.update(self, content, layout=layout)
        self._schedule_bottom_pin_reapply()
        return True

    @property
    def is_pinned_to_bottom(self) -> bool:
        """Whether this metadata panel is following the real document bottom."""
        return getattr(self, "_pinned_to_bottom", False)

    def pin_to_bottom(self) -> None:
        """Keep the metadata viewport pinned to the real document bottom."""
        if not self._section_view_features_enabled():
            return
        scroll = self._bottom_pin_container()
        self._pinned_to_bottom = True
        self._bottom_pin_last_y = int(scroll.scroll_y) if scroll is not None else -1
        self._schedule_bottom_pin_reapply()

    def release_bottom_pin(self) -> None:
        """Stop following the metadata document bottom."""
        self._pinned_to_bottom = False
        self._bottom_pin_last_y = -1

    def bottom_scroll_target(self, scroll: ScrollableContainer) -> int:
        """Return the real document bottom, excluding section-navigation reserve."""
        return max(0, int(scroll.max_scroll_y) - self.section_layout_reserve)

    def _bottom_pin_container(self) -> ScrollableContainer | None:
        parent = self.parent
        return parent if isinstance(parent, ScrollableContainer) else None

    def _schedule_bottom_pin_reapply(self) -> None:
        if not self.is_pinned_to_bottom or getattr(
            self, "_bottom_pin_reapply_scheduled", False
        ):
            return
        self._bottom_pin_reapply_scheduled = True
        try:
            self.call_after_refresh(self._reapply_bottom_pin)
        except Exception:
            self._bottom_pin_reapply_scheduled = False

    def _reapply_bottom_pin(self) -> None:
        self._bottom_pin_reapply_scheduled = False
        if not self.is_pinned_to_bottom:
            return
        scroll = self._bottom_pin_container()
        if scroll is None:
            return

        last_y = getattr(self, "_bottom_pin_last_y", -1)
        if (
            last_y >= 0
            and int(scroll.scroll_y) != last_y
            and int(scroll.max_scroll_y) >= last_y
        ):
            self.release_bottom_pin()
            return

        target = self.bottom_scroll_target(scroll)
        scroll.scroll_to(y=target, animate=False, immediate=True)
        self._bottom_pin_last_y = target

    def on_resize(self, event: events.Resize) -> None:
        """Re-apply the bottom pin when layout geometry changes."""
        handler = getattr(super(), "on_resize", None)
        if callable(handler):
            handler(event)
        self._schedule_bottom_pin_reapply()

    def render(self) -> SectionTrackingVisual:
        """Render original content through the lightweight section tracker."""
        generation = getattr(self, "_section_generation", 0)
        tracking_visual = getattr(self, "_section_tracking_visual", None)
        if (
            tracking_visual is None
            or getattr(self, "_section_tracking_visual_generation", -1) != generation
        ):
            tracking_visual = SectionTrackingVisual(
                self.visual,
                self,  # type: ignore[arg-type]
                generation,
                content_digest=getattr(self, "_section_content_digest", None),
            )
            self._section_tracking_visual = tracking_visual
            self._section_tracking_visual_generation = generation
        return tracking_visual

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        """Reserve enough non-document layout to top-align the final title."""
        real_height = super().get_content_height(container, viewport, width)
        self._section_real_content_height = real_height
        anchors = (
            self._section_anchors
            if self._section_anchor_generation == self._section_generation
            and self._section_anchor_width == width
            else ()
        )
        reserve = 0
        top_anchors = [
            anchor
            for anchor in anchors
            if anchor.role
            in (
                PromptPanelSectionRole.TITLE,
                PromptPanelSectionRole.CARD,
            )
        ]
        if (
            getattr(self, "_section_layout_reserve_enabled", False)
            and self._section_view_features_enabled()
            and top_anchors
        ):
            reserve = max(0, top_anchors[-1].row + container.height - real_height)
        self._section_layout_reserve = reserve
        return real_height + reserve

    def card_anchor_rows(self, *, width: int) -> tuple[tuple[str, int], ...] | None:
        """Return ordered ``(card_id, row)`` pairs, or None when not ready."""
        generation = getattr(self, "_section_generation", 0)
        ready = (
            getattr(self, "_section_anchor_generation", -1) == generation
            and getattr(self, "_section_anchor_width", -1) == width
        )
        if not ready:
            return None
        pairs: list[tuple[str, int]] = []
        for anchor in getattr(self, "_section_anchors", ()):
            if anchor.role is not PromptPanelSectionRole.CARD:
                continue
            identity = anchor.identity
            if identity.startswith("card:"):
                pairs.append((identity[len("card:") :], anchor.row))
            else:
                pairs.append((identity, anchor.row))
        return tuple(pairs)

    def enable_section_layout_reserve(self) -> bool:
        """Enable final-title alignment extent on the first navigation request."""
        if not self._section_view_features_enabled() or getattr(
            self, "_section_layout_reserve_enabled", False
        ):
            return False
        self._section_layout_reserve_enabled = True
        self.refresh(layout=True)
        return True

    def _publish_section_layout(
        self,
        *,
        generation: int,
        width: int,
        anchors: tuple[PromptPanelSectionAnchor, ...],
    ) -> None:
        """Publish anchors produced by the current content generation."""
        if generation != getattr(self, "_section_generation", 0):
            return
        self._section_anchor_generation = generation
        self._section_anchor_width = width
        self._section_anchors = anchors
        active = getattr(self, "_active_section_identity", None)
        if (
            active is not None
            and generation != self._preserve_missing_section_generation
            and all(
                anchor.identity != active
                for anchor in anchors
                if anchor.role is PromptPanelSectionRole.TITLE
            )
        ):
            self._active_section_identity = None

    def resolve_section_target(
        self,
        direction: int,
        *,
        width: int,
    ) -> PromptPanelSectionTarget:
        """Resolve an initial or adjacent section from the current render cache."""
        generation = getattr(self, "_section_generation", 0)
        ready = (
            getattr(self, "_section_anchor_generation", -1) == generation
            and getattr(self, "_section_anchor_width", -1) == width
        )
        if not ready:
            return PromptPanelSectionTarget(PromptPanelSectionTargetKind.NOT_READY)

        all_anchors: tuple[PromptPanelSectionAnchor, ...] = getattr(
            self, "_section_anchors", ()
        )
        anchors = tuple(
            anchor
            for anchor in all_anchors
            if anchor.role is PromptPanelSectionRole.TITLE
        )
        if not anchors:
            return PromptPanelSectionTarget(PromptPanelSectionTargetKind.EMPTY)

        active = getattr(self, "_active_section_identity", None)
        if active is None:
            index = 0 if direction > 0 else len(anchors) - 1
        else:
            index_by_identity = {
                anchor.identity: index for index, anchor in enumerate(anchors)
            }
            current_index = index_by_identity.get(active)
            if current_index is None:
                index = 0 if direction > 0 else len(anchors) - 1
            elif (direction > 0 and current_index == len(anchors) - 1) or (
                direction < 0 and current_index == 0
            ):
                self._active_section_identity = None
                return PromptPanelSectionTarget(PromptPanelSectionTargetKind.TOP)
            else:
                index = (current_index + direction) % len(anchors)

        target = anchors[index]
        self._active_section_identity = target.identity
        return PromptPanelSectionTarget(
            PromptPanelSectionTargetKind.ANCHOR,
            target,
        )

    def resolve_section_at_row(self, row: int, *, width: int) -> str | None:
        """Resolve the section occupying ``row`` from the current anchor cache."""
        generation = getattr(self, "_section_generation", 0)
        ready = (
            getattr(self, "_section_anchor_generation", -1) == generation
            and getattr(self, "_section_anchor_width", -1) == width
        )
        if not ready:
            return None

        current: str | None = None
        for anchor in getattr(self, "_section_anchors", ()):
            if anchor.role is PromptPanelSectionRole.CARD:
                continue
            if anchor.row > row:
                break
            current = anchor.identity
        return current

    def queue_section_retry(self, direction: int) -> None:
        """Retain one direction while refreshed anchors await first paint."""
        self._pending_section_direction = direction

    def consume_section_retry(self) -> int | None:
        """Return and clear the retained navigation direction."""
        direction = getattr(self, "_pending_section_direction", None)
        self._pending_section_direction = None
        return direction

    @property
    def active_section_identity(self) -> str | None:
        """Semantic identity selected by the section-navigation shortcuts."""
        return getattr(self, "_active_section_identity", None)

    @property
    def section_layout_reserve(self) -> int:
        """Current non-document trailing layout extent."""
        return getattr(self, "_section_layout_reserve", 0)


_UNSET = object()
_EMPTY_DOCUMENT = object()
