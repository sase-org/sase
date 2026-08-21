"""Xprompt loading and target state for ``PromptInputBar`` stacks."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from sase.ace.tui.widgets.prompt_stack import (
    PromptStackState,
    XPromptBinding,
    XPromptReadonlyTarget,
    split_frontmatter,
    split_prompt_text,
)
from sase.xprompt.prompt_frontmatter import PromptFrontmatter

if TYPE_CHECKING:
    from textual.widgets import Static as _MixinBase

    from sase.ace.tui.widgets._prompt_input_bar_stack_models import PromptFocusRestore
    from sase.ace.tui.widgets.prompt_stack import PromptStackItem
    from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
else:
    _MixinBase = object


class PromptInputBarStackXPromptMixin(_MixinBase):
    """Xprompt content loading, binding, and frontmatter helpers."""

    if TYPE_CHECKING:
        _readonly_xprompt_target: XPromptReadonlyTarget | None
        _mini_xprompt_focus_restore: PromptFocusRestore | None
        _snippet_focus_restore: PromptFocusRestore | None
        _stack: PromptStackState
        _xprompt_source_stale: bool
        _xprompt_target_generation: int

        def _pane_id(self, item: PromptStackItem) -> str: ...
        def _confirm_discard_dirty_snippet(
            self,
            proceed: Callable[[], None],
        ) -> bool: ...
        def _rebuild_stack(
            self,
            enter_mode: str | None = None,
            *,
            restore_focus: PromptFocusRestore | None = None,
        ) -> None: ...
        def _refresh_prompt_mode_subtitle(self) -> None: ...
        def _refresh_title(self, mode_suffix: str = "") -> None: ...
        def _resolve_pane_target(
            self, target_text_area: object, pane_id: str
        ) -> PromptTextArea | None: ...
        def _schedule_xprompt_stale_check(self, *, force: bool = False) -> None: ...
        def _sync_state_from_widgets(self) -> None: ...
        def mark_readonly_xprompt_target(
            self, target: XPromptReadonlyTarget
        ) -> None: ...
        def refresh_frontmatter_panel_from_stack(self) -> None: ...

    def load_stack_from_xprompt_markdown(
        self,
        text: str,
        *,
        binding: XPromptBinding | None = None,
        preserve_target: bool = False,
        read_only_target: XPromptReadonlyTarget | None = None,
    ) -> None:
        """Reload the whole bar from edited xprompt markdown (the multi-pane ``^G`` return).

        This always treats *text* as xprompt markdown via
        :meth:`PromptStackState.from_text`, lifting leading frontmatter into the
        shared stack frontmatter and splitting real ``---`` separators into
        panes.  The frontmatter panel is re-synced so the lifted frontmatter
        shows in the structured panel state.  Unlike the inline history load
        (:meth:`load_prompt_into_pane`), this replaces the whole stack and
        normalizes a lone body pane through the canonical splitter instead of
        keeping the body text verbatim.
        """
        self._sync_state_from_widgets()
        if self._stack.auxiliary_is_dirty:
            self._confirm_discard_dirty_snippet(
                lambda: self._load_stack_from_xprompt_markdown_after_snippet_guard(
                    text,
                    binding=binding,
                    preserve_target=preserve_target,
                    read_only_target=read_only_target,
                )
            )
            return

        self._load_stack_from_xprompt_markdown_after_snippet_guard(
            text,
            binding=binding,
            preserve_target=preserve_target,
            read_only_target=read_only_target,
        )

    def _load_stack_from_xprompt_markdown_after_snippet_guard(
        self,
        text: str,
        *,
        binding: XPromptBinding | None = None,
        preserve_target: bool = False,
        read_only_target: XPromptReadonlyTarget | None = None,
    ) -> None:
        """Reload the whole bar after the snippet-discard guard has passed."""
        previous_stack = self._stack if preserve_target else None
        previous_readonly_target = (
            self._readonly_xprompt_target if preserve_target else None
        )
        previous_stale = self._xprompt_source_stale if preserve_target else False
        self._stack = PromptStackState.from_text(text)
        if hasattr(self, "_snippet_focus_restore"):
            self._snippet_focus_restore = None
        if hasattr(self, "_mini_xprompt_focus_restore"):
            self._mini_xprompt_focus_restore = None
        self._rebuild_stack()
        if binding is not None:
            self.target_xprompt(binding, source_markdown=text)
        elif read_only_target is not None:
            self.mark_readonly_xprompt_target(read_only_target)
        elif (
            preserve_target
            and previous_stack is not None
            and previous_stack.binding is not None
        ):
            self._readonly_xprompt_target = None
            self._stack.binding = previous_stack.binding
            self._stack._clean_content_hash = previous_stack._clean_content_hash
            self._stack._bound_source_markdown = previous_stack._bound_source_markdown
            self._stack._bound_source_texts = previous_stack._bound_source_texts
            self._xprompt_source_stale = previous_stale
            self._xprompt_target_generation += 1
            self._refresh_target_classes()
            self._refresh_title()
            self._refresh_prompt_mode_subtitle()
            self._schedule_xprompt_stale_check(force=True)
        elif preserve_target and previous_readonly_target is not None:
            self.mark_readonly_xprompt_target(previous_readonly_target)
        else:
            self._readonly_xprompt_target = None
            self._xprompt_source_stale = False
            self._xprompt_target_generation += 1
            self._refresh_target_classes()
            self._refresh_title()
            self._refresh_prompt_mode_subtitle()
        self.refresh_frontmatter_panel_from_stack()

    def target_xprompt(
        self,
        binding: XPromptBinding,
        *,
        source_markdown: str | None = None,
    ) -> None:
        """Set the xprompt definition this prompt stack edits."""
        self._readonly_xprompt_target = None
        self._xprompt_source_stale = False
        self._xprompt_target_generation += 1
        self._stack.bind(binding, source_markdown=source_markdown)
        self._refresh_target_classes()
        self._refresh_title()
        self._refresh_prompt_mode_subtitle()
        self.refresh_frontmatter_panel_from_stack()
        self._schedule_xprompt_stale_check(force=True)

    def clear_xprompt_target(self) -> None:
        """Clear the current xprompt target from the prompt stack."""
        self._stack.unbind()
        self._readonly_xprompt_target = None
        self._xprompt_source_stale = False
        self._xprompt_target_generation += 1
        self._refresh_target_classes()
        self._refresh_title()
        self._refresh_prompt_mode_subtitle()

    def xprompt_target(self) -> XPromptBinding | None:
        """Return the current xprompt target, if any."""
        return self._stack.binding

    def _refresh_target_classes(self) -> None:
        binding = self._stack.binding
        readonly = getattr(self, "_readonly_xprompt_target", None) is not None
        stale = bool(getattr(self, "_xprompt_source_stale", False))
        has_target = binding is not None or readonly
        self.set_class(has_target, "xprompt-target")
        self.set_class(has_target and self._stack.is_dirty, "dirty")
        self.set_class(readonly, "readonly")
        self.set_class(binding is not None and stale, "stale")

    def update_active_pane(self, text: str) -> None:
        """Replace only the active pane's text with *text* (the ``^G`` path).

        Used when the external editor is opened on one pane of a multi-pane
        stack: the edit applies to that pane alone, leaving the rest of the
        stack — and its order — intact.  The edited text is loaded verbatim
        (embedded ``---`` is left in the pane and resolved by the launch parser
        on a later whole-stack submit), and the pane is re-focused for typing.
        """
        self._sync_state_from_widgets()
        if self._stack.selected_item.is_auxiliary_pane:
            return
        self._stack.selected_item.text = text
        self._rebuild_stack(enter_mode="insert")

    def load_prompt_into_pane(
        self, target_text_area: object, pane_id: str, text: str
    ) -> bool:
        """Load a history entry into the origin pane, preserving the rest of the stack.

        The inline ``Ctrl+I`` history-load path: unlike a whole-stack replace,
        *text* (the VCS-substituted history entry) loads into the exact pane the
        user opened the history modal from -- resolved through the same staleness
        guard the ``#@`` selector uses -- while every other pane keeps its live
        text and relative order.

        A single-segment body replaces just that pane's text (kept verbatim, the
        ``lift_frontmatter=True`` single-pane path, so an xprompt-swarm
        invocation or a plain prompt stays one pane); a multi-segment body (real
        ``---`` separators outside fences/frontmatter) replaces the pane with its
        first stripped segment and inserts one new pane per remaining segment
        directly below, in order.  Leading frontmatter is lifted: a non-empty
        block overwrites the stack's frontmatter (the conflict confirmation runs
        in the app layer *before* this is called); an incoming-empty block leaves
        the current frontmatter untouched.

        Returns ``False`` without touching any pane when the captured target is
        stale (its pane or bar was unmounted/rebuilt while the modal was open),
        so the caller can notify and leave every prompt unchanged.
        """
        text_area = self._resolve_pane_target(target_text_area, pane_id)
        if text_area is None:
            return False

        # Sync live edits from every pane back into the model first (like
        # ``update_active_pane``), so panes the user touched while the modal was
        # open survive the rebuild.
        self._sync_state_from_widgets()

        index = self._pane_index_for(text_area)
        if index is None:
            return False
        if self._stack.items[index].is_auxiliary_pane:
            return False

        frontmatter, body = split_frontmatter(text)
        segments = split_prompt_text(body)
        if len(segments) <= 1:
            # A single-segment body is kept verbatim rather than stripped,
            # matching ``PromptStackState.single(lift_frontmatter=True)``.
            segments = [body]

        self._stack.load_segments_at(index, segments)
        if frontmatter:
            self._stack.frontmatter = frontmatter

        self._rebuild_stack(enter_mode="insert")
        self.refresh_frontmatter_panel_from_stack()
        return True

    def _pane_index_for(self, text_area: PromptTextArea) -> int | None:
        """Return the stack index whose pane widget is *text_area*, else ``None``."""
        for index, item in enumerate(self._stack.items):
            if self._pane_id(item) == text_area.id:
                return index
        return None

    def has_frontmatter_properties(self) -> bool:
        """True when the stack currently carries non-empty xprompt properties.

        Drives the history-load conflict check: an incoming entry with its own
        frontmatter must not silently clobber properties the user already
        staged.  A non-empty frontmatter string that parses to a non-``is_empty``
        :class:`PromptFrontmatter` counts; a non-empty string that fails to parse
        (mid-edit YAML) is conservatively treated as properties present, so a
        confirmation is shown rather than silently overwriting the draft.
        """
        raw = self._stack.frontmatter
        if not raw:
            return False
        try:
            return not PromptFrontmatter.parse(raw).is_empty
        except Exception:
            return True

    def current_frontmatter(self) -> str:
        """Return the stack's current raw frontmatter string (``""`` when unset)."""
        return self._stack.frontmatter
