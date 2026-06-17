"""Non-visual state model for the multi-agent prompt stack.

This module is the deterministic foundation for the stacked prompt UI: it
models an ordered list of prompt items, the currently active (focused) item,
and the structural operations the later UI phases drive (navigate, reorder,
insert, remove, split, join).  It deliberately contains **no** Textual widgets
so that all stack behavior can be unit-tested without a running app.

Canonical split/join semantics mirror agent dispatch:

- Splitting initial text reuses the Rust-backed multi-prompt parser via
  :func:`sase.agent.multi_prompt.split_segments_protecting_fences`, so ``---``
  inside fenced code blocks and YAML frontmatter delimiters are never treated
  as segment separators.
- Joining produces a multi-prompt string with ``\n---\n`` between non-empty
  items, matching the whole-stack submit contract described in the
  ``multi_agent_prompt_stack`` design.

Frontmatter is preserved on the state (not modeled as an agent pane) so that a
later whole-stack submit can re-attach it, keeping ``split -> join`` lossless.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sase.agent.multi_prompt import split_segments_protecting_fences
from sase.xprompt._fenced_blocks import (
    protect_fenced_blocks,
    unprotect_fenced_blocks,
)
from sase.xprompt.loader_parsing import parse_yaml_front_matter
from sase.xprompt.prompt_frontmatter import PromptFrontmatter

# A line that is exactly ``---`` (trailing whitespace allowed, no leading
# whitespace) is a segment separator — the same rule the canonical multi-prompt
# parser uses.  Kept local so live splitting does not depend on a private regex
# in another module.
_SEPARATOR_LINE_RE = re.compile(r"^---\s*$", re.MULTILINE)


def split_prompt_text(text: str) -> list[str]:
    """Split *text* into prompt segments using canonical multi-prompt parsing.

    Thin wrapper over :func:`split_segments_protecting_fences` so callers in the
    TUI layer have a single, intention-revealing entry point.  Empty and
    whitespace-only segments are dropped, fenced ``---`` is protected, and
    leading YAML frontmatter is consumed rather than split.
    """
    return split_segments_protecting_fences(text)


def _split_preserving_empty(body: str) -> list[str] | None:
    """Split *body* on real ``---`` separator lines, keeping empty segments.

    Like :func:`split_prompt_text` this protects fenced code blocks so ``---``
    inside a fence is never a separator, but unlike it the empty segments a real
    separator produces are preserved.  That keeps a freshly typed trailing
    ``---`` meaningful: it yields a new empty bottom pane to draft in rather than
    being dropped.  Returns ``None`` when *body* has no real separator so callers
    can cheaply skip the no-op case.
    """
    blocks: list[str] = []
    protected = protect_fenced_blocks(body, blocks)
    parts = _SEPARATOR_LINE_RE.split(protected)
    if len(parts) <= 1:
        return None
    return [unprotect_fenced_blocks(part, blocks).strip("\n") for part in parts]


def _extract_frontmatter(text: str) -> tuple[str, str]:
    """Return ``(raw_frontmatter, body)`` for *text*.

    ``raw_frontmatter`` is the leading YAML frontmatter block including its
    opening and closing ``---`` delimiters (no trailing newline), or ``""`` when
    *text* has no valid frontmatter.  ``body`` is the remaining text after the
    frontmatter, matching :func:`parse_yaml_front_matter` exactly so that
    splitting the body stays consistent with agent dispatch.
    """
    frontmatter, body = parse_yaml_front_matter(text)
    if frontmatter is None:
        return "", text

    lines = text.split("\n")
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[: index + 1]), body
    # Unreachable: parse_yaml_front_matter only returns a dict when a closing
    # delimiter exists, but fall back to "no frontmatter" defensively.
    return "", text


@dataclass
class PromptStackItem:
    """A single prompt pane's state.

    ``text`` is the only field exercised by the Phase 1 model operations; the
    remaining fields carry per-pane editor state that later UI phases bind to a
    ``PromptTextArea`` (cursor position, vim mode, and the last rendered height
    used for stack sizing).  They are preserved across reorder/insert so that
    moving a pane never resets its editing context.
    """

    text: str
    item_id: str
    cursor: tuple[int, int] = (0, 0)
    mode: str = "insert"
    last_height: int | None = None


@dataclass
class PromptStackState:
    """Ordered prompt items plus the active selection.

    Order is top-to-bottom launch order.  By convention the active/newest
    editable item is the bottom item unless the user navigates elsewhere.  The
    stack always holds at least one item (which may be empty while drafting).
    """

    items: list[PromptStackItem] = field(default_factory=list)
    selected_index: int = 0
    frontmatter: str = ""
    _next_id: int = field(default=0, repr=False)

    # -- construction ---------------------------------------------------------

    @classmethod
    def single(cls, text: str = "") -> PromptStackState:
        """Create a one-item stack from *text* verbatim (no splitting)."""
        return cls._from_texts([text])

    @classmethod
    def from_panes(
        cls, texts: list[str], *, selected_index: int | None = None
    ) -> PromptStackState:
        """Create a stack with exactly one verbatim pane per entry in *texts*.

        Unlike :meth:`from_text`, no entry is split on ``---`` and no leading
        frontmatter is lifted: each string becomes exactly one pane.  This is
        the seeding path for bulk kill-and-edit, where every killed agent must
        map to exactly one editable pane even when its raw prompt embeds
        separators or YAML frontmatter.  Empty *texts* yields a single empty
        drafting pane; the default active pane is the last one.
        """
        if not texts:
            texts = [""]
        if selected_index is None:
            selected_index = len(texts) - 1
        return cls._from_texts(texts, selected_index=selected_index)

    @classmethod
    def from_text(cls, text: str) -> PromptStackState:
        """Create a stack by canonically splitting *text* into panes.

        Leading frontmatter is preserved on the state rather than becoming a
        pane.  If *text* has no real segments (empty/whitespace only), the stack
        still holds a single empty drafting item.  The bottom item is the
        default active item after splitting.
        """
        frontmatter, body = _extract_frontmatter(text)
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
        """All item texts, top-to-bottom."""
        return [item.text for item in self.items]

    @property
    def is_effectively_empty(self) -> bool:
        """True when no item has non-whitespace text."""
        return not any(item.text.strip() for item in self.items)

    def join(self, *, include_frontmatter: bool = True) -> str:
        """Join non-empty items into a multi-prompt string.

        Items are stripped and empty ones dropped, then joined with ``\n---\n``
        to match the canonical multi-prompt format.  When frontmatter is present
        and *include_frontmatter* is set, it is re-attached above the body.
        """
        body = "\n---\n".join(
            stripped
            for stripped in (item.text.strip() for item in self.items)
            if stripped
        )
        if include_frontmatter and self.frontmatter:
            return f"{self.frontmatter}\n{body}" if body else self.frontmatter
        return body

    def attach_frontmatter(self, body: str) -> str:
        """Prepend prompt-level frontmatter to *body* for a single-pane submit.

        A single pane launched on its own (``<enter>`` while the stack still has
        panes) must carry the stack's prompt-level YAML frontmatter so any local
        xprompt definitions it references still resolve at launch — matching what
        :meth:`join` re-attaches for the whole-stack submit.  When there is no
        frontmatter (or no body) *body* is returned unchanged.
        """
        if self.frontmatter and body:
            return f"{self.frontmatter}\n{body}"
        return body

    # -- structured frontmatter ----------------------------------------------

    @property
    def frontmatter_model(self) -> PromptFrontmatter:
        """The structured editing view over the raw :attr:`frontmatter` string.

        Parsed on demand so the raw string stays the source of truth for the
        byte-stable :meth:`join`/:meth:`attach_frontmatter` contract; the panel
        edits this model and writes it back via :meth:`set_frontmatter_model`.
        """
        return PromptFrontmatter.parse(self.frontmatter)

    def set_frontmatter_model(self, model: PromptFrontmatter) -> None:
        """Write *model* back as the canonical raw :attr:`frontmatter` string.

        An empty model clears the frontmatter entirely (no stray ``---\\n---``),
        keeping a later :meth:`join` free of empty delimiters.
        """
        self.frontmatter = model.serialize()

    # -- selection ------------------------------------------------------------

    def _clamp(self, index: int) -> int:
        return max(0, min(index, len(self.items) - 1))

    def focus(self, index: int) -> int:
        """Set the active item to *index* (clamped); return the clamped value."""
        self.selected_index = self._clamp(index)
        return self.selected_index

    def move_focus(self, delta: int) -> bool:
        """Move the active item by *delta* (e.g. ``,j``/``,k``).

        Returns ``True`` when the selection changed.
        """
        target = self._clamp(self.selected_index + delta)
        if target == self.selected_index:
            return False
        self.selected_index = target
        return True

    # -- mutation -------------------------------------------------------------

    def insert_below(self, text: str = "", *, select: bool = True) -> PromptStackItem:
        """Insert a new item directly below the active item."""
        item = self._new_item(text)
        position = self.selected_index + 1
        self.items.insert(position, item)
        if select:
            self.selected_index = position
        else:
            self.selected_index = self._clamp(self.selected_index)
        return item

    def append_bottom(self, text: str = "", *, select: bool = True) -> PromptStackItem:
        """Append a new item at the bottom of the stack (the ``-`` keymap)."""
        item = self._new_item(text)
        self.items.append(item)
        if select:
            self.selected_index = len(self.items) - 1
        return item

    def remove_selected(self) -> bool:
        """Remove the active item when others remain.

        Returns ``False`` (without mutating) when only one item is left, so the
        caller can fall back to the existing "Empty prompt - cancelled" /
        unmount behavior.  Otherwise removes the item and clamps the selection
        onto the nearest remaining item.
        """
        if len(self.items) <= 1:
            return False
        del self.items[self.selected_index]
        self.selected_index = self._clamp(self.selected_index)
        return True

    def move_selected(self, delta: int) -> bool:
        """Reorder the active item by *delta* (``Ctrl+Shift+H``/``Ctrl+Shift+L``).

        The moved item stays selected.  Returns ``True`` when the item moved.
        """
        target = self._clamp(self.selected_index + delta)
        if target == self.selected_index:
            return False
        item = self.items.pop(self.selected_index)
        self.items.insert(target, item)
        self.selected_index = target
        return True

    def split_selected(self) -> bool:
        """Canonically split the active item in place.

        When the active item's text parses into more than one segment, the item
        is replaced by one item per segment (preserving order) and the bottom
        new item becomes active.  Returns ``True`` when a split occurred.
        """
        segments = split_prompt_text(self.selected_item.text)
        if len(segments) <= 1:
            return False
        replacement = [self._new_item(segment) for segment in segments]
        position = self.selected_index
        self.items[position : position + 1] = replacement
        self.selected_index = position + len(replacement) - 1
        return True

    def split_selected_live(self) -> bool:
        """Split the active item on a freshly typed ``---`` separator line.

        Unlike :meth:`split_selected`, empty leading/trailing segments produced
        by a real separator are kept as panes, so typing ``---`` at the end of a
        pane yields a new empty bottom pane to keep drafting in.  Frontmatter
        typed above the first pane is lifted onto the state so a later
        whole-stack ``join`` stays lossless.  Separators inside fenced code
        blocks or YAML frontmatter delimiters never trigger a split.  Returns
        ``True`` when a split occurred and the bottom new pane becomes active.
        """
        item = self.selected_item
        if self.selected_index == 0:
            frontmatter, body = _extract_frontmatter(item.text)
        else:
            # Only the first pane can carry prompt-level frontmatter; treat any
            # leading ``---`` block in a later pane as plain body text.
            frontmatter, body = "", item.text
        segments = _split_preserving_empty(body)
        if segments is None:
            return False
        if frontmatter and not self.frontmatter:
            self.frontmatter = frontmatter
        replacement = [self._new_item(segment) for segment in segments]
        position = self.selected_index
        self.items[position : position + 1] = replacement
        self.selected_index = position + len(replacement) - 1
        return True

    # -- internal -------------------------------------------------------------

    def _new_item(self, text: str) -> PromptStackItem:
        item = PromptStackItem(text=text, item_id=f"p{self._next_id}")
        self._next_id += 1
        return item


__all__ = [
    "PromptStackItem",
    "PromptStackState",
    "split_prompt_text",
]
