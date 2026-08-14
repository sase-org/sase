"""Shared stable-target navigation contract for every Artifacts pane."""

from __future__ import annotations

from abc import ABCMeta, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass

from rich.text import Text
from textual.message_pump import _MessagePumpMeta

#: Bump when the token encoding changes shape; old tokens become invalid.
_TOKEN_VERSION = "v1"
#: ASCII Unit Separator: safe against arbitrary identifier content
#: (shas, paths, titles, Unicode) since it cannot appear in a valid part.
_TOKEN_DELIMITER = "\x1f"

#: Legacy leading-tuple kinds mapped to their owning pane, for staged
#: migration and tests. Any other kind is treated as a document-provider
#: pane (``ref:<kind>``).
_LEGACY_KIND_TO_PANE_ID: dict[str, str] = {
    "commit": "stitches",
    "bead": "beads",
    "file": "files",
    "patch": "patches",
}


@dataclass(frozen=True, slots=True)
class ArtifactEntryTarget:
    """Immutable, serializable identity for one selectable Artifacts row.

    ``pane_id`` names the owning pane (``"stitches"``, ``"beads"``,
    ``"files"``, ``"patches"``, or ``"ref:<kind>"`` for a document-provider
    pane) so identical ``parts`` in two different panes never collide and a
    cross-pane request can resolve its destination from the target alone.
    """

    pane_id: str
    parts: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.pane_id:
            raise ValueError("ArtifactEntryTarget requires a non-empty pane_id")
        if _TOKEN_DELIMITER in self.pane_id:
            raise ValueError(
                "ArtifactEntryTarget pane_id must not contain the token delimiter"
            )
        for part in self.parts:
            if not isinstance(part, str):
                raise TypeError(
                    f"ArtifactEntryTarget parts must be strings, got {part!r}"
                )
            if _TOKEN_DELIMITER in part:
                raise ValueError(
                    "ArtifactEntryTarget part must not contain the token delimiter"
                )

    def to_token(self) -> str:
        """Return the canonical, versioned, delimiter-safe token encoding."""
        return _TOKEN_DELIMITER.join((_TOKEN_VERSION, self.pane_id, *self.parts))

    @classmethod
    def from_token(cls, token: str) -> ArtifactEntryTarget:
        """Parse a token produced by :meth:`to_token`.

        Raises ``ValueError`` for malformed tokens: wrong/missing version
        marker or a missing pane id.
        """
        segments = token.split(_TOKEN_DELIMITER)
        if len(segments) < 2 or segments[0] != _TOKEN_VERSION or not segments[1]:
            raise ValueError(f"malformed artifact entry token: {token!r}")
        return cls(pane_id=segments[1], parts=tuple(segments[2:]))

    @classmethod
    def from_legacy(cls, value: tuple[str, ...]) -> ArtifactEntryTarget:
        """Convert a pre-typed ``(kind, *parts)`` tuple.

        Kept narrow and explicit for staged migration and tests — every
        checked-in production row-target helper constructs
        :class:`ArtifactEntryTarget` directly instead.
        """
        if not value:
            raise ValueError("empty legacy artifact entry target")
        kind, *rest = value
        pane_id = _LEGACY_KIND_TO_PANE_ID.get(kind, f"ref:{kind}")
        return cls(pane_id=pane_id, parts=tuple(rest))


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
    def request_entry_target(self, target: ArtifactEntryTarget) -> bool:
        """Select a target now, or remember it for the next loaded row model."""

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
        try:
            current_index = targets.index(current) if current is not None else None
        except ValueError:
            current_index = None
        if current_index is None:
            current_index = 0 if offset >= 0 else len(targets) - 1
        target = targets[max(0, min(len(targets) - 1, current_index + offset))]
    else:
        return False
    return navigator.select_entry_target(target)


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
    "prepend_jump_hint",
    "prepend_mark_glyph",
    "select_relative_entry",
]
