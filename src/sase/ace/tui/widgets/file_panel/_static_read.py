"""Off-thread static file read helpers for the agent file panel."""

import os
from dataclasses import dataclass

from ...graphics import is_supported_image_path
from ._messages import _EXTENSION_TO_LEXER


@dataclass
class StaticReadResult:
    """Result of an off-thread static file/diff read.

    ``request_id`` lets the UI thread drop superseded results when the user
    navigates between files faster than reads complete. ``path`` is the
    original path passed in (used for path-match stale checks against the
    current file list); ``expanded_path`` is the user-expanded form actually
    opened.
    """

    request_id: int
    mode: str  # "file" or "diff"
    path: str
    expanded_path: str
    status: str  # "ok" | "missing" | "empty" | "image"
    content: str | None = None
    lexer: str = "text"


def read_static_file(request_id: int, path: str, mode: str) -> StaticReadResult:
    """Worker-thread entry point that reads a static file or diff from disk."""
    expanded_path = os.path.expanduser(path)
    if mode == "file" and is_supported_image_path(expanded_path):
        return StaticReadResult(
            request_id=request_id,
            mode=mode,
            path=path,
            expanded_path=expanded_path,
            status="image",
        )
    try:
        with open(expanded_path, encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return StaticReadResult(
            request_id=request_id,
            mode=mode,
            path=path,
            expanded_path=expanded_path,
            status="missing",
        )
    if not content.strip():
        return StaticReadResult(
            request_id=request_id,
            mode=mode,
            path=path,
            expanded_path=expanded_path,
            status="empty",
        )
    if mode == "file":
        _, ext = os.path.splitext(expanded_path)
        lexer = _EXTENSION_TO_LEXER.get(ext.lower(), "text")
    else:
        lexer = "diff"
    return StaticReadResult(
        request_id=request_id,
        mode=mode,
        path=path,
        expanded_path=expanded_path,
        status="ok",
        content=content,
        lexer=lexer,
    )


def normalized_static_path(path: str | None) -> str | None:
    if not path:
        return None
    return os.path.normcase(os.path.abspath(os.path.expanduser(path)))
