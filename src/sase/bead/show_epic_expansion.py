"""Parse and resolve ``<epic-id>..`` expansion tokens for ``sase bead show``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sase.bead.model import Issue

EXPANSION_SUFFIX = ".."


class ExpansionError(ValueError):
    """A malformed ``<epic-id>..`` expansion token."""


def expansion_stem(token: str) -> str | None:
    """Return the stem of an expansion token, or ``None`` if not one.

    Raises ``ExpansionError`` for a token that ends in ``..`` but whose stem
    is empty or itself ends in ``.`` -- the two malformed spellings a user
    can plausibly type (``..`` and ``tt...``).
    """
    if not token.endswith(EXPANSION_SUFFIX):
        return None
    stem = token[: -len(EXPANSION_SUFFIX)]
    if not stem or stem.endswith("."):
        raise ExpansionError(
            f"invalid ID expansion: {token!r} "
            "(expected <epic-id>.., for example sase-tt..)"
        )
    return stem


def expand_epic_target(view: Any, stem: str) -> list[str]:
    """Return the stem plus its direct children, ordered per phase number.

    Raises ``KeyError`` when ``stem`` is a shorthand ID that does not
    resolve; a full-form ID that does not resolve instead yields ``[stem]``
    unchanged, since it has no children to find.
    """
    children = view.get_epic_children(stem)
    return [stem, *(child.id for child in _ordered_children(children))]


def _ordered_children(children: list[Issue]) -> list[Issue]:
    """Sort by the integer suffix after the final dot; keep the rest in place."""
    numbered: list[tuple[int, Issue]] = []
    unnumbered: list[Issue] = []
    for child in children:
        suffix = child.id.rsplit(".", 1)[-1]
        if suffix.isdigit():
            numbered.append((int(suffix), child))
        else:
            unnumbered.append(child)
    numbered.sort(key=lambda pair: pair[0])
    return [child for _, child in numbered] + unnumbered


__all__ = [
    "EXPANSION_SUFFIX",
    "ExpansionError",
    "expand_epic_target",
    "expansion_stem",
]
