"""Shared diff-path extraction semantics for workflow step outputs.

A workflow step's output is a free-form ``dict`` of named artifacts.  Only an
output field literally named ``diff_path`` is a diff that the ACE file panel may
render as unified-diff text.

The historical fallback promoted the *first* output field whose schema type was
``"path"`` into ``diff_path``.  That conflated arbitrary file artifacts
(``local_path``, ``plan_path``, ``project_file``, image paths, ...) with diffs.
For ``#sshot`` the ``local_path`` PNG output was a valid ``"path"`` field but
not a diff, so the file panel tried to ``read_text()`` binary PNG bytes as UTF-8
and crashed the TUI with a ``UnicodeDecodeError``.

Keeping this logic in one place ensures every loader and the runner finalization
path agree on what counts as a diff.
"""

from __future__ import annotations

from typing import Any


def diff_path_from_step_output(output: Any) -> str | None:
    """Return the explicit ``diff_path`` from a single workflow step's output.

    Only an output field literally named ``diff_path`` counts as a diff.  The
    workflow executor is the authority that decides what a diff is and writes
    that explicit key (e.g. for embedded ``#gh`` + ``#pr`` workflows); loaders
    and runner finalization must not guess a diff from arbitrary ``"path"``
    fields.

    Returns ``None`` when *output* is not a dict or carries no non-empty
    ``diff_path`` value.
    """
    if isinstance(output, dict):
        value = output.get("diff_path")
        if value:
            return str(value)
    return None
