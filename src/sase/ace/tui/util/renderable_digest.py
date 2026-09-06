"""Stable content digests for Rich renderable trees.

Idle TUI refreshes rebuild prompt-panel documents as new Group/Text objects
with the same visible content. Hashing the tree by content (not identity)
lets render caches survive those rebuilds.
"""

from __future__ import annotations

from hashlib import blake2b
from typing import Any

from rich.console import Group
from rich.style import Style
from rich.syntax import Syntax
from rich.text import Text

from .lazy_syntax import CachedRenderable


def renderable_content_digest(node: object) -> str:
    """Return a content hash for ``node`` that ignores object identity."""
    hasher = blake2b(digest_size=16)
    _update_digest(hasher, node)
    return hasher.hexdigest()


def _update_digest(hasher: Any, node: object) -> None:
    if isinstance(node, CachedRenderable):
        hasher.update(b"C")
        hasher.update(node.content_digest.encode("ascii"))
        return
    if isinstance(node, Syntax):
        hasher.update(b"S")
        hasher.update(node.code.encode("utf-8", errors="replace"))
        lexer = getattr(node, "lexer", None)
        hasher.update(repr(lexer).encode("utf-8", errors="replace"))
        theme = getattr(node, "theme", "")
        hasher.update(str(theme).encode("utf-8", errors="replace"))
        return
    if isinstance(node, Text):
        _update_text_digest(hasher, node)
        return
    if isinstance(node, Group):
        hasher.update(b"G")
        for child in node.renderables:
            _update_digest(hasher, child)
        return
    if isinstance(node, str):
        hasher.update(b"s")
        hasher.update(node.encode("utf-8", errors="replace"))
        return
    if isinstance(node, bytes):
        hasher.update(b"b")
        hasher.update(node)
        return

    plain = getattr(node, "plain", None)
    spans = getattr(node, "spans", None)
    if isinstance(plain, str):
        hasher.update(b"H")
        hasher.update(plain.encode("utf-8", errors="replace"))
        hasher.update(str(getattr(node, "end", "")).encode("utf-8", errors="replace"))
        if spans:
            for span in spans:
                hasher.update(
                    f"{span.start}:{span.end}:{_style_digest_token(span.style)}".encode(
                        "utf-8", errors="replace"
                    )
                )
        sections = getattr(node, "_sections", None)
        if sections:
            for start, end, section in sections:
                hasher.update(
                    f"{start}:{end}:{type(section).__name__}".encode(
                        "utf-8", errors="replace"
                    )
                )
                logical = getattr(section, "logical_text", None)
                if logical is not None:
                    _update_digest(hasher, logical)
        return

    markup = getattr(node, "markup", None)
    if isinstance(markup, str):
        hasher.update(b"M")
        hasher.update(markup.encode("utf-8", errors="replace"))
        return

    hasher.update(type(node).__name__.encode("utf-8", errors="replace"))
    hasher.update(repr(node).encode("utf-8", errors="replace")[:2048])


def _update_text_digest(hasher: Any, node: Text) -> None:
    hasher.update(b"T")
    hasher.update(node.plain.encode("utf-8", errors="replace"))
    hasher.update(str(node.end).encode("utf-8", errors="replace"))
    for span in node.spans:
        hasher.update(
            f"{span.start}:{span.end}:{_style_digest_token(span.style)}".encode(
                "utf-8", errors="replace"
            )
        )


def _style_digest_token(style: object) -> str:
    if not isinstance(style, Style):
        return str(style)
    token = str(style)
    if not style.meta:
        return token
    meta = ",".join(f"{key}={style.meta[key]!r}" for key in sorted(style.meta))
    return f"{token}|meta:{meta}"


__all__ = ["renderable_content_digest"]
