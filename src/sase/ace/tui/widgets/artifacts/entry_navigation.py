"""Shared stable-target navigation contract for every Artifacts pane."""

from __future__ import annotations

from abc import ABCMeta, abstractmethod
from collections.abc import Mapping
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, cast

from rich.text import Text
from textual.message_pump import _MessagePumpMeta
from textual.widgets import OptionList

from sase.core.artifact_relation_layout import RelationEntryFact, RelationRole
from sase.core.artifact_entry_target import ArtifactEntryTarget

if TYPE_CHECKING:
    from sase.ace.link_reveal import HostQueryProbe
    from sase.ace.query.profile_evaluator_types import ArtifactQueryRowInput


class LinkRequestState(Enum):
    """Outcome of one pane's attempt to satisfy an entry-target request.

    ``PENDING`` keeps a host link-follow transaction open until the pane
    reports a later, authoritative outcome through the shared completion
    seam (:meth:`ArtifactEntryNavigator._complete_entry_request`) -- loading
    is never conflated with absence.
    """

    SELECTED = auto()
    PENDING = auto()
    MISSING = auto()
    FAILED = auto()


class _ArtifactEntryNavigatorMeta(ABCMeta, _MessagePumpMeta):
    """Combine ``ABCMeta`` with Textual's metaclass.

    Every concrete implementer of :class:`ArtifactEntryNavigator` is also a
    Textual widget (or a mixin composed into one), and Textual widgets use
    their own metaclass (``_MessagePumpMeta``, the metaclass of
    ``Widget``/``MessagePump``). A plain ``abc.ABC`` base would conflict
    with that metaclass at class-creation time, so the navigator uses this
    combined one instead — it keeps real abstractness enforcement (a pane
    missing a method fails at construction with ``TypeError``) while
    staying mixable with ``Widget``/``Vertical``/``Horizontal`` subclasses.
    """


class ArtifactEntryNavigator(metaclass=_ArtifactEntryNavigatorMeta):
    """Complete contract implemented by every live Artifacts pane."""

    @abstractmethod
    def entry_targets(self) -> tuple[ArtifactEntryTarget, ...]:
        """Return selectable entry identities in current visual order."""

    @abstractmethod
    def selected_entry_target(self) -> ArtifactEntryTarget | None:
        """Return the currently selected stable identity, if any."""

    @abstractmethod
    def select_entry_target(self, target: ArtifactEntryTarget) -> bool:
        """Select and focus a currently visible target."""

    @abstractmethod
    def request_entry_target(
        self,
        target: ArtifactEntryTarget,
        *,
        generation: int | None = None,
    ) -> LinkRequestState:
        """Select a target now, or remember it for the next loaded row model.

        ``generation`` is an opaque host-owned link-follow transaction token;
        implementers must retain it beside their pending-target state and
        pass it back unchanged to :meth:`_complete_entry_request` when a
        deferred request later resolves. Callers outside the link-follow
        coordinator (e.g. ``Ctrl+O`` trail restoration) omit it, in which
        case a later async resolution is never reported to the host.
        """

    @abstractmethod
    def apply_entry_jump_hints(
        self,
        hints: Mapping[ArtifactEntryTarget, str],
    ) -> None:
        """Repaint selectable rows with transient adaptive jump hints."""

    @abstractmethod
    def clear_entry_jump_hints(self) -> None:
        """Remove transient jump hints while preserving selection."""

    @abstractmethod
    def apply_entry_marks(
        self,
        marks: set[ArtifactEntryTarget],
    ) -> None:
        """Repaint rows using the app-owned stable-target mark set."""

    @abstractmethod
    def conditional_footer_entries(self) -> tuple[tuple[str, str], ...]:
        """Return action names and labels that depend on the selected row."""

    def entry_target_index(self, target: ArtifactEntryTarget) -> int | None:
        """Return the target's visual index when the pane has a cached lookup."""
        del target
        return None

    def relation_entry_facts(
        self,
    ) -> Mapping[ArtifactEntryTarget, RelationEntryFact]:
        """Return presentation facts used by the host relation panel."""
        return {}

    def reveal_entry_target(
        self,
        target: ArtifactEntryTarget,
        *,
        role: RelationRole,
    ) -> bool:
        """Reveal a same-pane relation target that is not currently visible."""
        del target, role
        return False

    def entry_target_for_ref(
        self, kind: str, payload: str
    ) -> ArtifactEntryTarget | None:
        """Resolve a link-graph ref to this pane's own row identity.

        Answered from the pane's *unfiltered* snapshot, so a filtered-out
        row still resolves -- which is what lets the host build a reveal
        for it. The default degrades to "no answer" for panes with no
        relation index (never a fabricated target) by reusing the same
        known-row-identity set the relation panel already resolves
        against, via the Phase 1 sase-core matching facade.
        """
        index_getter = getattr(self, "relation_index", None)
        index = index_getter() if callable(index_getter) else None
        if index is None:
            return None
        from sase.ace.tui.relations.artifact_links import known_target_for_ref

        return known_target_for_ref(kind, payload, index.known_targets)

    def expand_fold_for_entry_target(self, target: ArtifactEntryTarget) -> bool:
        """Expand the minimum fold hiding *target*; no query change.

        Returns ``True`` when a collapsed fold was expanded. The default
        is a no-op so panes without grouping still construct.
        """
        del target
        return False

    def close_host_filter_session(self) -> None:
        """Close any open inline filter editor before a host query rewrite."""

    def host_query_row_for_target(
        self, target: ArtifactEntryTarget
    ) -> ArtifactQueryRowInput | None:
        """Return the profile-query row entry backing *target*.

        Answered from this pane's unfiltered snapshot, or ``None`` when
        the pane cannot answer (no snapshot, unknown target).
        """
        del target
        return None

    def host_query_probe(self, target: ArtifactEntryTarget) -> HostQueryProbe | None:
        """Build a one-row matcher for *target*, or ``None`` when unavailable."""
        from sase.ace.link_reveal import build_host_query_probe

        return build_host_query_probe(
            self.host_query_row_for_target(target),
            getattr(self, "_query_profile", None),
        )

    def _complete_entry_request(
        self,
        state: LinkRequestState,
    ) -> LinkRequestState:
        """Clear this pane's pending target and report the outcome once.

        The single seam every implementer's deferred (and immediate)
        completion routes through -- whether the resolution happens inline
        within :meth:`request_entry_target` or later from an async refresh --
        so the host link-follow coordinator sees a matching generation
        exactly once. Reports nothing when no generation was retained
        (a non-link-follow caller, or no pending request was open).
        """
        generation = getattr(self, "_pending_entry_generation", None)
        self._pending_entry_target = None
        self._pending_entry_generation = None
        if generation is not None:
            app = getattr(self, "app", None)
            reporter = getattr(app, "_complete_link_follow_request", None)
            if callable(reporter):
                reporter(generation, state)
        return state

    def record_relation_origin(self, origin: ArtifactEntryTarget) -> None:
        """Record a jump-back origin before relation navigation leaves it."""
        app = getattr(self, "app", None)
        if app is None:
            return
        history = getattr(app, "_artifacts_jump_history", None)
        if isinstance(history, dict):
            history[origin.pane_id] = origin


def select_relative_entry(
    navigator: ArtifactEntryNavigator,
    *,
    offset: int | None = None,
    boundary: str | None = None,
) -> bool:
    """Resolve and select a target from the pane's current visual model.

    ``offset`` counts selectable targets and clamps at either boundary.  A
    missing selection starts at the first target for non-negative movement
    and the last target for negative movement.
    """
    targets = navigator.entry_targets()
    if not targets:
        return False
    if boundary == "first":
        target = targets[0]
    elif boundary == "last":
        target = targets[-1]
    elif offset is not None:
        current = navigator.selected_entry_target()
        current_index = (
            navigator.entry_target_index(current) if current is not None else None
        )
        if current_index is not None and (
            current_index < 0
            or current_index >= len(targets)
            or targets[current_index] != current
        ):
            current_index = None
        if current_index is None and current is not None:
            try:
                current_index = targets.index(current)
            except ValueError:
                current_index = None
        if current_index is None:
            current_index = 0 if offset >= 0 else len(targets) - 1
        target = targets[max(0, min(len(targets) - 1, current_index + offset))]
    else:
        return False
    return navigator.select_entry_target(target)


def prewarm_option_render_cache(
    option_list: OptionList,
    *,
    max_options: int = 512,
) -> bool:
    """Warm bounded normal/highlighted OptionList row render caches."""
    if not option_list.is_mounted or not option_list.scrollable_content_region:
        return False
    dynamic_option_list = cast(Any, option_list)
    normal_style = option_list.get_visual_style("option-list--option")
    highlighted_style = option_list.get_visual_style(
        "option-list--option",
        "option-list--option-highlighted",
    )
    disabled_style = option_list.get_visual_style(
        "option-list--option",
        "option-list--option-disabled",
    )
    for index in range(min(option_list.option_count, max_options)):
        option = option_list.get_option_at_index(index)
        if option.disabled:
            dynamic_option_list._get_option_render(option, disabled_style)
            continue
        dynamic_option_list._get_option_render(option, normal_style)
        dynamic_option_list._get_option_render(option, highlighted_style)
    return True


def reveal_option_list_highlight(
    option_list: OptionList,
    *,
    allow_future_growth: bool = False,
) -> None:
    """Reveal the highlighted option with slack for relation-panel relayout."""
    option_list.scroll_to_highlight()
    highlighted = option_list.highlighted
    if highlighted is None or not option_list.is_mounted:
        return
    option_list._update_lines()
    try:
        line = option_list._index_to_line[highlighted]
        row_height = option_list._heights[highlighted]
    except KeyError:
        return
    viewport_height = option_list.scrollable_content_region.height
    target_y = max(0, line + row_height - viewport_height + 1)
    if not allow_future_growth:
        target_y = min(option_list.max_scroll_y, target_y)
    if target_y > option_list.scroll_y:
        option_list.scroll_to(y=target_y, animate=False, force=True)


def schedule_option_list_highlight_reveal(
    option_list: OptionList,
    *,
    allow_future_growth: bool = False,
) -> None:
    """Reveal now and after Textual has applied any relation-panel relayout."""
    reveal_option_list_highlight(
        option_list,
        allow_future_growth=allow_future_growth,
    )

    def reveal_after_refresh() -> None:
        reveal_option_list_highlight(
            option_list,
            allow_future_growth=allow_future_growth,
        )
        option_list.call_after_refresh(
            lambda: reveal_option_list_highlight(
                option_list,
                allow_future_growth=allow_future_growth,
            )
        )
        option_list.call_later(
            lambda: reveal_option_list_highlight(
                option_list,
                allow_future_growth=allow_future_growth,
            )
        )

    option_list.call_later(
        lambda: reveal_option_list_highlight(
            option_list,
            allow_future_growth=allow_future_growth,
        )
    )
    option_list.call_after_refresh(reveal_after_refresh)


def prepend_jump_hint(prompt: Text, hint: str | None) -> Text:
    """Return a row prompt with the standard compact jump marker."""
    if hint is None:
        return prompt
    text = Text()
    text.append(f"[{hint}] ", style="bold #FFFF00")
    text.append_text(prompt.copy())
    return text


def prepend_mark_glyph(prompt: Text, marked: bool) -> Text:
    """Return a row prompt with the standard mark glyph when marked."""
    if not marked:
        return prompt
    text = Text()
    text.append("[✓] ", style="bold #00D700")
    text.append_text(prompt.copy())
    return text


__all__ = [
    "ArtifactEntryNavigator",
    "ArtifactEntryTarget",
    "LinkRequestState",
    "RelationEntryFact",
    "prepend_jump_hint",
    "prepend_mark_glyph",
    "prewarm_option_render_cache",
    "reveal_option_list_highlight",
    "schedule_option_list_highlight_reveal",
    "select_relative_entry",
]
