"""Pure editing state for an ordered stack of agent prompts."""

from __future__ import annotations

from dataclasses import dataclass, field

from sase.xprompt.prompt_frontmatter import PromptFrontmatter

from ._prompt_stack_binding import PromptStackBindingMixin
from ._prompt_stack_parsing import split_frontmatter, split_prompt_text
from ._prompt_stack_targets import SnippetPaneTarget, XPromptBinding


@dataclass
class PromptStackItem:
    """A single prompt pane's state.

    ``text`` is the primary model value.  The remaining fields carry per-pane
    editor state bound to a ``PromptTextArea`` and survive reorder/insert
    operations so moving a pane never resets its editing context.
    """

    text: str
    item_id: str
    cursor: tuple[int, int] = (0, 0)
    mode: str = "insert"
    last_height: int | None = None
    snippet_target: SnippetPaneTarget | None = None

    @property
    def is_snippet_pane(self) -> bool:
        """Return whether this item is the pane-scoped snippet draft."""
        return self.snippet_target is not None


@dataclass
class PromptStackState(PromptStackBindingMixin):
    """Ordered prompt items plus the active selection.

    Order is top-to-bottom launch order.  By convention the active/newest
    editable item is the bottom item unless the user navigates elsewhere.  The
    stack always holds at least one item (which may be empty while drafting).
    """

    items: list[PromptStackItem] = field(default_factory=list)
    selected_index: int = 0
    frontmatter: str = ""
    binding: XPromptBinding | None = None
    _clean_content_hash: str | None = field(default=None, repr=False)
    _bound_source_markdown: str | None = field(default=None, repr=False)
    _bound_source_texts: tuple[str, ...] | None = field(default=None, repr=False)
    _next_id: int = field(default=0, repr=False)

    # -- construction ---------------------------------------------------------

    @classmethod
    def single(
        cls, text: str = "", *, lift_frontmatter: bool = False
    ) -> PromptStackState:
        """Create a one-item stack from *text* without splitting.

        By default *text* is stored verbatim.  When *lift_frontmatter* is set,
        any leading YAML frontmatter block is stored on the stack and the
        remaining body becomes the lone pane, preserving the body text returned
        by the shared launch parser.
        """
        if lift_frontmatter:
            frontmatter, body = split_frontmatter(text)
            return cls._from_texts([body], frontmatter=frontmatter)
        return cls._from_texts([text])

    @classmethod
    def from_panes(
        cls, texts: list[str], *, selected_index: int | None = None
    ) -> PromptStackState:
        """Create a stack with exactly one verbatim pane per entry in *texts*.

        Unlike :meth:`from_text`, no entry is split on ``---`` and no leading
        frontmatter is lifted.  Empty *texts* yields a single empty drafting
        pane; the default active pane is the last one.
        """
        if not texts:
            texts = [""]
        if selected_index is None:
            selected_index = len(texts) - 1
        return cls._from_texts(texts, selected_index=selected_index)

    @classmethod
    def from_text(cls, text: str) -> PromptStackState:
        """Create a stack by canonically splitting *text* into panes."""
        frontmatter, body = split_frontmatter(text)
        segments = split_prompt_text(body)
        if not segments:
            segments = [""]
        return cls._from_texts(
            segments,
            frontmatter=frontmatter,
            selected_index=len(segments) - 1,
        )

    @classmethod
    def _from_texts(
        cls,
        texts: list[str],
        *,
        frontmatter: str = "",
        selected_index: int = 0,
    ) -> PromptStackState:
        state = cls(items=[], selected_index=0, frontmatter=frontmatter)
        for text in texts:
            state.items.append(state._new_item(text))
        state.selected_index = state._clamp(selected_index)
        return state

    # -- queries --------------------------------------------------------------

    def __len__(self) -> int:
        return len(self.items)

    @property
    def selected_item(self) -> PromptStackItem:
        """The currently active item."""
        return self.items[self.selected_index]

    @property
    def texts(self) -> list[str]:
        """Agent prompt texts, top-to-bottom."""
        return self.agent_texts

    @property
    def snippet_index(self) -> int | None:
        """The mounted index of the snippet pane, if present."""
        for index, item in enumerate(self.items):
            if item.is_snippet_pane:
                return index
        return None

    @property
    def snippet_item(self) -> PromptStackItem | None:
        """The pinned bottom snippet item, if present."""
        index = self.snippet_index
        return self.items[index] if index is not None else None

    @property
    def has_snippet_pane(self) -> bool:
        """Return whether the stack currently includes a snippet pane."""
        return self.snippet_item is not None

    @property
    def agent_items(self) -> list[PromptStackItem]:
        """Prompt items that participate in launch, stash, and save-as payloads."""
        return [item for item in self.items if not item.is_snippet_pane]

    @property
    def agent_texts(self) -> list[str]:
        """Agent prompt texts, top-to-bottom."""
        return [item.text for item in self.agent_items]

    @property
    def agent_count(self) -> int:
        """Number of agent prompt panes, excluding the snippet pane."""
        return len(self.agent_items)

    @property
    def snippet_is_dirty(self) -> bool:
        """Return whether the snippet draft differs from its loaded body."""
        item = self.snippet_item
        if item is None or item.snippet_target is None:
            return False
        return item.text.strip() != (item.snippet_target.loaded_body or "")

    @property
    def is_effectively_empty(self) -> bool:
        """True when no agent item has non-whitespace text."""
        return not any(item.text.strip() for item in self.agent_items)

    def join(self, *, include_frontmatter: bool = True) -> str:
        """Join non-empty items into a canonical multi-prompt string."""
        body = "\n---\n".join(
            stripped
            for stripped in (item.text.strip() for item in self.agent_items)
            if stripped
        )
        if include_frontmatter and self.frontmatter:
            return f"{self.frontmatter}\n{body}" if body else self.frontmatter
        return body

    def editor_markdown(self) -> str:
        """Render the whole stack as spaced markdown for the all-pane editor.

        This uses the same non-empty pane selection as :meth:`join`, but pads
        separators with blank lines for human editing.  The result round-trips
        through :meth:`from_text`.
        """
        body = "\n\n---\n\n".join(
            stripped
            for stripped in (item.text.strip() for item in self.agent_items)
            if stripped
        )
        if self.frontmatter:
            return f"{self.frontmatter}\n\n{body}" if body else self.frontmatter
        return body

    def attach_frontmatter(self, body: str) -> str:
        """Prepend prompt-level frontmatter to a non-empty single-pane body."""
        if self.frontmatter and body:
            return f"{self.frontmatter}\n{body}"
        return body

    # -- structured frontmatter ----------------------------------------------

    @property
    def frontmatter_model(self) -> PromptFrontmatter:
        """Return the structured editing view over the raw frontmatter."""
        return PromptFrontmatter.parse(self.frontmatter)

    def set_frontmatter_model(self, model: PromptFrontmatter) -> None:
        """Store *model* as canonical raw frontmatter."""
        self.frontmatter = model.serialize()

    # -- selection ------------------------------------------------------------

    def _clamp(self, index: int) -> int:
        return max(0, min(index, len(self.items) - 1))

    def focus(self, index: int) -> int:
        """Set the active item to *index* (clamped); return the clamped value."""
        self.selected_index = self._clamp(index)
        return self.selected_index

    def move_focus(self, delta: int) -> bool:
        """Cycle active-item focus by *delta*, wrapping at the stack edges."""
        if len(self.items) <= 1:
            return False
        target = (self.selected_index + delta) % len(self.items)
        if target == self.selected_index:
            return False
        self.selected_index = target
        return True

    # -- mutation -------------------------------------------------------------

    def insert_below(self, text: str = "", *, select: bool = True) -> PromptStackItem:
        """Insert a new item directly below the active item."""
        item = self._new_item(text)
        snippet_index = self.snippet_index
        position = self.selected_index + 1
        if snippet_index is not None:
            position = min(position, snippet_index)
        self.items.insert(position, item)
        if select:
            self.selected_index = position
        elif position <= self.selected_index:
            self.selected_index += 1
        else:
            self.selected_index = self._clamp(self.selected_index)
        return item

    def append_bottom(self, text: str = "", *, select: bool = True) -> PromptStackItem:
        """Append a new item at the bottom of the stack (the ``g-`` keymap)."""
        item = self._new_item(text)
        snippet_index = self.snippet_index
        if snippet_index is None:
            self.items.append(item)
            position = len(self.items) - 1
        else:
            position = snippet_index
            self.items.insert(position, item)
        if select:
            self.selected_index = position
        elif position <= self.selected_index:
            self.selected_index += 1
        return item

    def append_snippet_pane(
        self, text: str, target: SnippetPaneTarget
    ) -> PromptStackItem:
        """Append the single pinned bottom snippet pane and focus it."""
        if self.snippet_item is not None:
            raise ValueError("prompt stack already has a snippet pane")
        item = self._new_item(text, snippet_target=target)
        self.items.append(item)
        self.selected_index = len(self.items) - 1
        return item

    def remove_snippet_pane(self) -> PromptStackItem | None:
        """Remove and return the snippet pane, leaving agent panes intact."""
        index = self.snippet_index
        if index is None:
            return None
        item = self.items.pop(index)
        if self.selected_index > index:
            self.selected_index -= 1
        else:
            self.selected_index = self._clamp(self.selected_index)
        return item

    def retarget_snippet_pane(self, target: SnippetPaneTarget) -> None:
        """Replace the snippet target without touching the draft body."""
        item = self.snippet_item
        if item is None:
            raise ValueError("prompt stack has no snippet pane")
        item.snippet_target = target

    def remove_selected(self) -> bool:
        """Remove the active item when another applicable item remains."""
        if not self.selected_item.is_snippet_pane and self.agent_count <= 1:
            return False
        del self.items[self.selected_index]
        self.selected_index = self._clamp(self.selected_index)
        return True

    def move_selected(self, delta: int) -> bool:
        """Cycle the active agent item by *delta*, keeping it selected."""
        if len(self.items) <= 1 or self.selected_item.is_snippet_pane:
            return False
        target = (self.selected_index + delta) % len(self.items)
        if self.items[target].is_snippet_pane:
            return False
        if target == self.selected_index:
            return False
        item = self.items.pop(self.selected_index)
        self.items.insert(target, item)
        self.selected_index = target
        return True

    def split_selected(self) -> bool:
        """Canonically split the active item in place."""
        if self.selected_item.is_snippet_pane:
            return False
        segments = split_prompt_text(self.selected_item.text)
        if len(segments) <= 1:
            return False
        replacement = [self._new_item(segment) for segment in segments]
        position = self.selected_index
        self.items[position : position + 1] = replacement
        self.selected_index = position + len(replacement) - 1
        return True

    def load_segments_at(self, index: int, segments: list[str]) -> None:
        """Load *segments* at *index*, keeping all other items intact."""
        if not segments:
            segments = [""]
        index = self._clamp(index)
        if self.items[index].is_snippet_pane:
            return
        self.items[index].text = segments[0]
        additions = [self._new_item(segment) for segment in segments[1:]]
        self.items[index + 1 : index + 1] = additions
        self.selected_index = index

    # -- internal -------------------------------------------------------------

    def _new_item(
        self,
        text: str,
        *,
        snippet_target: SnippetPaneTarget | None = None,
    ) -> PromptStackItem:
        item = PromptStackItem(
            text=text,
            item_id=f"p{self._next_id}",
            snippet_target=snippet_target,
        )
        self._next_id += 1
        return item


__all__ = ["PromptStackItem", "PromptStackState"]
