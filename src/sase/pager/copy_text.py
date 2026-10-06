"""Pager clipboard text never carries an artifact-kind label.

Copying a painted link or a section yields the reference's bare argument
(path, bead ID, SHA, ``repo@sha`` …), never the leading ``<kind>:`` label.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sase.artifact_ref_kinds import parsable_artifact_ref_kinds
from sase.artifact_ref_operations import parse_artifact_ref

if TYPE_CHECKING:
    from sase.pager.link_context import LinkResolutionContext

__all__ = ["copy_text_for_reference", "strip_reference_kind"]

_KIND_LABEL_RE = re.compile(r"[a-z][a-z0-9_-]*\Z")


def strip_reference_kind(
    ref: str, *, known_kinds: tuple[str, ...] | None = None
) -> str:
    """Remove one leading ``@`` plus a ``<kind>:`` label from *ref*.

    When *known_kinds* is ``None`` the span is a reference by construction,
    so any label matching the kind grammar is stripped. Otherwise the label
    must be in the compiled kind catalog or *known_kinds*. Anything that
    would leave an empty argument, a URL (``//`` argument), or an unknown
    label copies unchanged.
    """
    if not ref:
        return ref
    text = ref[1:] if ref.startswith("@") else ref
    label, separator, argument = text.partition(":")
    if not separator or not argument:
        return ref
    if argument.startswith("//"):
        return ref
    if _KIND_LABEL_RE.fullmatch(label) is None:
        return ref
    if known_kinds is not None:
        allowed = set(parsable_artifact_ref_kinds()) | set(known_kinds)
        if label not in allowed:
            return ref
    return argument


def copy_text_for_reference(
    ref: str,
    *,
    context: LinkResolutionContext | None = None,
    known_kinds: tuple[str, ...] | None = None,
) -> str:
    """Return clipboard text for one artifact reference *ref*.

    Digest-form indexed files resolve to their stored file path (canonical
    ref only when resolution fails, so ``explicit:<hex>`` is never copied).
    Everything else strips the ``<kind>:`` label via
    :func:`strip_reference_kind`. Gated (``yy``) refs expand the allowed
    kinds with ``known_kinds_from_link_context`` lazily, only when the
    cheaper sets miss and the text looks labeled.
    """
    if not ref:
        return ref
    digest = _digest_file_path(ref, context=context)
    if digest is not None:
        return digest
    if known_kinds is None:
        return strip_reference_kind(ref)
    stripped = strip_reference_kind(ref, known_kinds=known_kinds)
    if stripped != ref:
        return stripped
    if context is None or not _looks_labeled(ref):
        return ref
    from sase.pager.known_kinds import known_kinds_from_link_context

    try:
        extra = known_kinds_from_link_context(context)
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        return ref
    if not extra:
        return ref
    return strip_reference_kind(ref, known_kinds=(*known_kinds, *extra))


def _looks_labeled(ref: str) -> bool:
    """Return whether *ref* has a grammar-shaped ``<kind>:arg`` label."""
    if not ref:
        return False
    text = ref[1:] if ref.startswith("@") else ref
    label, separator, argument = text.partition(":")
    if not separator or not argument or argument.startswith("//"):
        return False
    return _KIND_LABEL_RE.fullmatch(label) is not None


def _digest_file_path(ref: str, *, context: LinkResolutionContext | None) -> str | None:
    """Return the stored path for digest-form ``file:`` refs, if any.

    Returns ``None`` when *ref* is not digest-form, so callers fall through
    to label stripping. Returns *ref* unchanged when resolution fails, so
    the canonical form (not ``explicit:<hex>``) is copied.
    """
    candidate = ref[1:] if ref.startswith("@") else ref
    try:
        parsed = parse_artifact_ref(candidate)
    except (ImportError, RuntimeError, ValueError):
        return None
    if parsed.payload.type != "file":
        return None
    from sase.artifact_cli.references import (
        resolve_cli_reference,
        resolved_file_path,
    )
    from sase.pager.owner import artifact_context_for_link_context

    artifact_context = (
        None if context is None else artifact_context_for_link_context(context)
    )
    try:
        if artifact_context is None:
            result = resolve_cli_reference(candidate)
        else:
            result = resolve_cli_reference(candidate, context=artifact_context)
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        return ref
    try:
        path = resolved_file_path(result)
    except (ImportError, OSError, RuntimeError, ValueError):
        return ref
    if path is None:
        return ref
    return str(path)
