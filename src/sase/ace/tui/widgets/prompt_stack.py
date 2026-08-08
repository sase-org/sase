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

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
from typing import Literal

from sase.agent.multi_prompt import split_segments_protecting_fences
from sase.xprompt.loader_parsing import parse_yaml_front_matter
from sase.xprompt.prompt_frontmatter import PromptFrontmatter
from sase.xprompt.save import SaveTargetFormat


@dataclass(frozen=True)
class SourceFingerprint:
    """Disk identity used to reject silent writes over external changes."""

    mtime_ns: int
    size: int
    content_hash: str

    @classmethod
    def from_path(cls, path: str | Path) -> SourceFingerprint:
        source = Path(path)
        data = source.read_bytes()
        stat = source.stat()
        return cls(stat.st_mtime_ns, stat.st_size, hashlib.sha256(data).hexdigest())

    @staticmethod
    def stat_signature(path: str | Path) -> tuple[int, int] | None:
        """Return a cheap ``(mtime_ns, size)`` signature for display staleness."""
        try:
            stat = Path(path).stat()
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size

    def matches_stat(self, path: str | Path) -> bool:
        """Return whether *path* still has this fingerprint's stat metadata."""
        return self.stat_signature(path) == (self.mtime_ns, self.size)


@dataclass(frozen=True)
class XPromptBinding:
    """The editable xprompt source a prompt stack writes back to."""

    kind: Literal["file", "config"]
    path: str
    write_path: str
    apply_target: str | None
    via_chezmoi: bool
    reference: str
    target_format: SaveTargetFormat
    loaded_fingerprint: SourceFingerprint
    entry_name: str | None = None

    @classmethod
    def for_file(
        cls,
        path: str | Path,
        *,
        reference: str | None = None,
    ) -> XPromptBinding:
        from sase.xprompt.write_targets import (
            canonical_reference_for_path,
            resolve_xprompt_write_target,
        )

        target = resolve_xprompt_write_target(path)
        return cls(
            kind="file",
            path=str(target.read_path),
            write_path=str(target.write_path),
            apply_target=(
                str(target.apply_target) if target.apply_target is not None else None
            ),
            via_chezmoi=target.via_chezmoi,
            reference=canonical_reference_for_path(
                target.read_path,
                write_path=target.write_path,
                reference=reference,
            ),
            target_format=SaveTargetFormat.MARKDOWN,
            loaded_fingerprint=SourceFingerprint.from_path(target.write_path),
        )

    @classmethod
    def for_config(
        cls,
        path: str | Path,
        entry_name: str,
        *,
        reference: str | None = None,
    ) -> XPromptBinding:
        from sase.xprompt.write_targets import (
            canonical_reference_for_path,
            resolve_xprompt_write_target,
        )

        target = resolve_xprompt_write_target(path)
        return cls(
            kind="config",
            path=str(target.read_path),
            write_path=str(target.write_path),
            apply_target=(
                str(target.apply_target) if target.apply_target is not None else None
            ),
            via_chezmoi=target.via_chezmoi,
            reference=canonical_reference_for_path(
                target.read_path,
                write_path=target.write_path,
                entry_name=entry_name,
                reference=reference,
            ),
            target_format=SaveTargetFormat.CONFIG,
            loaded_fingerprint=SourceFingerprint.from_path(target.write_path),
            entry_name=entry_name,
        )

    @property
    def name(self) -> str:
        return self.entry_name or Path(self.path).stem


@dataclass(frozen=True)
class XPromptReadonlyTarget:
    """A loaded xprompt definition that can be inspected but not overwritten."""

    reference: str
    path: str | None = None


def split_prompt_text(text: str) -> list[str]:
    """Split *text* into prompt segments using canonical multi-prompt parsing.

    Thin wrapper over :func:`split_segments_protecting_fences` so callers in the
    TUI layer have a single, intention-revealing entry point.  Empty and
    whitespace-only segments are dropped, fenced ``---`` is protected, and
    leading YAML frontmatter is consumed rather than split.
    """
    return split_segments_protecting_fences(text)


def split_frontmatter(text: str) -> tuple[str, str]:
    """Return ``(raw_frontmatter, body)`` for *text*.

    ``raw_frontmatter`` is the leading YAML frontmatter block including its
    opening and closing ``---`` delimiters (no trailing newline), or ``""`` when
    *text* has no valid frontmatter.  ``body`` is the remaining text after the
    frontmatter, matching :func:`parse_yaml_front_matter` exactly so that
    splitting the body stays consistent with agent dispatch.

    Public so the app layer can inspect an incoming prompt's frontmatter
    (e.g. a history entry) without loading it into the bar.
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

    @property
    def is_dirty(self) -> bool:
        """Whether a bound stack differs from its last loaded/written form."""
        if self.binding is None or self._clean_content_hash is None:
            return False
        return self._draft_hash() != self._clean_content_hash

    def bind(
        self, binding: XPromptBinding, *, source_markdown: str | None = None
    ) -> None:
        self.binding = binding
        self._clean_content_hash = self._draft_hash()
        self._bound_source_markdown = source_markdown
        self._bound_source_texts = (
            tuple(self.texts) if source_markdown is not None else None
        )

    def unbind(self) -> None:
        self.binding = None
        self._clean_content_hash = None
        self._bound_source_markdown = None
        self._bound_source_texts = None

    def source_changed(self) -> bool:
        binding = self.binding
        if binding is None:
            return False
        try:
            return (
                SourceFingerprint.from_path(binding.write_path)
                != binding.loaded_fingerprint
            )
        except OSError:
            return True

    def source_stat_changed(self) -> bool:
        """Return a cheap staleness hint without reading source bytes."""
        binding = self.binding
        if binding is None:
            return False
        return not binding.loaded_fingerprint.matches_stat(binding.write_path)

    def mark_written(
        self,
        *,
        source_markdown: str | None = None,
        loaded_fingerprint: SourceFingerprint | None = None,
    ) -> None:
        binding = self.binding
        if binding is None:
            return
        if loaded_fingerprint is None:
            loaded_fingerprint = SourceFingerprint.from_path(binding.write_path)
        self.binding = XPromptBinding(
            kind=binding.kind,
            path=binding.path,
            write_path=binding.write_path,
            apply_target=binding.apply_target,
            via_chezmoi=binding.via_chezmoi,
            reference=binding.reference,
            target_format=binding.target_format,
            entry_name=binding.entry_name,
            loaded_fingerprint=loaded_fingerprint,
        )
        self._clean_content_hash = self._draft_hash()
        if source_markdown is not None:
            self._bound_source_markdown = source_markdown
            self._bound_source_texts = tuple(self.texts)

    def markdown_preserving_unchanged_body(
        self, frontmatter: PromptFrontmatter
    ) -> str | None:
        """Replace only frontmatter when a bound Markdown body is untouched."""
        source = self._bound_source_markdown
        if source is None or self._bound_source_texts != tuple(self.texts):
            return None
        old_frontmatter, _ = split_frontmatter(source)
        new_frontmatter = frontmatter.serialize()
        if old_frontmatter:
            remainder = source[len(old_frontmatter) :]
            return (
                new_frontmatter + remainder
                if new_frontmatter
                else remainder.lstrip("\r\n")
            )
        if new_frontmatter:
            return f"{new_frontmatter}\n\n{source}"
        return source

    def _draft_hash(self) -> str:
        return hashlib.sha256(self.join().encode("utf-8")).hexdigest()

    def editor_markdown(self) -> str:
        """Render the whole stack as spaced markdown for the all-pane editor.

        Same non-empty/stripped pane selection as :meth:`join`, but formatted
        for human editing rather than dispatch: prompt bodies are separated by
        blank-line-padded ``---`` lines (``\n\n---\n\n``) and any prompt-level
        frontmatter is followed by a blank line before the first body.  With no
        non-empty bodies this returns just the frontmatter block (or ``""``),
        matching :meth:`join`'s empty-body behavior with no trailing blank
        spacer.  The spaced output round-trips back through :meth:`from_text`,
        whose canonical splitter drops the surrounding blank segments.
        """
        body = "\n\n---\n\n".join(
            stripped
            for stripped in (item.text.strip() for item in self.items)
            if stripped
        )
        if self.frontmatter:
            return f"{self.frontmatter}\n\n{body}" if body else self.frontmatter
        return body

    def attach_frontmatter(self, body: str) -> str:
        """Prepend prompt-level frontmatter to *body* for a single-pane submit.

        A single pane launched on its own while the stack still has panes must
        carry the stack's prompt-level YAML frontmatter so any local xprompt
        definitions it references still resolve at launch — matching what
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
        """Cycle active-item focus by *delta*, wrapping at the stack edges.

        With more than one item the target index wraps with modulo arithmetic,
        so ``delta`` ``-1`` from the top item selects the bottom item and ``+1``
        from the bottom item selects the top.  A single-item stack has no other
        item to focus, so it stays put.  Returns ``True`` when the selection
        changed.
        """
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
        position = self.selected_index + 1
        self.items.insert(position, item)
        if select:
            self.selected_index = position
        else:
            self.selected_index = self._clamp(self.selected_index)
        return item

    def append_bottom(self, text: str = "", *, select: bool = True) -> PromptStackItem:
        """Append a new item at the bottom of the stack (the ``g-`` keymap)."""
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
        """Cycle the active item by *delta* (the normal-mode ``Up``/``Down`` keys).

        With more than one item the target index wraps with modulo arithmetic,
        so ``delta`` ``-1`` from the top item moves it to the bottom and ``+1``
        from the bottom item moves it to the top.  The moved item stays
        selected.  A single-item stack cannot move, so it stays put.  Returns
        ``True`` when the item moved.
        """
        if len(self.items) <= 1:
            return False
        target = (self.selected_index + delta) % len(self.items)
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

    def load_segments_at(self, index: int, segments: list[str]) -> None:
        """Load *segments* into the stack at *index*, keeping other items intact.

        The item at *index* has its text replaced with the first segment (an
        empty *segments* list behaves as ``[""]``, clearing that item's text);
        one new item is inserted directly below for each subsequent segment, in
        order.  Every other item — above *index* or below the inserted run —
        keeps its text and relative order.  The selection stays on *index*
        (clamped), so the item that received the first segment stays active.

        Mirrors :meth:`split_selected`'s in-place replacement, but sources the
        segments from an explicit list (a loaded history entry) rather than
        re-splitting the item's own text.
        """
        if not segments:
            segments = [""]
        index = self._clamp(index)
        self.items[index].text = segments[0]
        additions = [self._new_item(segment) for segment in segments[1:]]
        self.items[index + 1 : index + 1] = additions
        self.selected_index = index

    # -- internal -------------------------------------------------------------

    def _new_item(self, text: str) -> PromptStackItem:
        item = PromptStackItem(text=text, item_id=f"p{self._next_id}")
        self._next_id += 1
        return item


__all__ = [
    "PromptStackItem",
    "PromptStackState",
    "SourceFingerprint",
    "XPromptBinding",
    "XPromptReadonlyTarget",
    "split_frontmatter",
    "split_prompt_text",
]
