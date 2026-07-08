"""Shared editor command resolution."""

from __future__ import annotations

import os
import shlex
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

EditorSource = Literal["VISUAL", "EDITOR", "fallback"]
EditorResolutionStatus = Literal["resolved", "missing", "unverified_shell"]
WhichFunc = Callable[[str], str | None]

_EDITOR_ENV_VARS: tuple[EditorSource, ...] = ("VISUAL", "EDITOR")
_FALLBACK_EDITORS = ("nvim", "vim")
_SHELL_META_CHARS = frozenset("\n`|&;<>")


@dataclass(frozen=True, slots=True)
class EditorResolution:
    """Resolved editor command metadata."""

    source: EditorSource
    raw_value: str
    argv: tuple[str, ...]
    head: str
    resolved_path: str | None
    status: EditorResolutionStatus

    @property
    def command_name(self) -> str:
        """Return the basename of the selected command head."""
        return os.path.basename(self.head)

    @property
    def command_string(self) -> str:
        """Return a shell-display form of the parsed argv."""
        return shlex.join(self.argv)

    @property
    def configured(self) -> bool:
        """Return whether the editor came from ``VISUAL`` or ``EDITOR``."""
        return self.source in _EDITOR_ENV_VARS

    def argv_with_path(self, path: str) -> list[str]:
        """Return argv for opening *path* with the selected editor."""
        return [*self.argv, path]


def resolve_editor(
    *,
    env: Mapping[str, str] | None = None,
    which: WhichFunc | None = None,
) -> EditorResolution:
    """Resolve the editor SASE should use.

    ``VISUAL`` has precedence over ``EDITOR``. Configured commands are parsed
    with :func:`shlex.split` so values such as ``code --wait`` are represented
    as argv. Without a configured editor, ``nvim`` and then ``vim`` are tried.
    """
    environ = os.environ if env is None else env
    which_func = shutil.which if which is None else which
    for source in _EDITOR_ENV_VARS:
        raw_value = environ.get(source, "")
        if raw_value.strip():
            return _resolve_configured_editor(source, raw_value, which=which_func)

    for command in _FALLBACK_EDITORS:
        resolved_path = which_func(command)
        if resolved_path is not None:
            return EditorResolution(
                source="fallback",
                raw_value=command,
                argv=(command,),
                head=command,
                resolved_path=resolved_path,
                status="resolved",
            )

    return EditorResolution(
        source="fallback",
        raw_value=_FALLBACK_EDITORS[-1],
        argv=(_FALLBACK_EDITORS[-1],),
        head=_FALLBACK_EDITORS[-1],
        resolved_path=None,
        status="missing",
    )


def _resolve_configured_editor(
    source: EditorSource,
    raw_value: str,
    *,
    which: WhichFunc,
) -> EditorResolution:
    stripped = raw_value.strip()
    try:
        argv = tuple(shlex.split(stripped))
    except ValueError:
        return EditorResolution(
            source=source,
            raw_value=raw_value,
            argv=(stripped,),
            head=stripped,
            resolved_path=None,
            status="unverified_shell",
        )

    if not argv:
        return EditorResolution(
            source=source,
            raw_value=raw_value,
            argv=(stripped,),
            head=stripped,
            resolved_path=None,
            status="missing",
        )

    head = argv[0]
    resolved_path = which(head)
    status: EditorResolutionStatus
    if _looks_like_shell_command(stripped):
        status = "unverified_shell"
    elif resolved_path is None:
        status = "missing"
    else:
        status = "resolved"

    return EditorResolution(
        source=source,
        raw_value=raw_value,
        argv=argv,
        head=head,
        resolved_path=resolved_path,
        status=status,
    )


def _looks_like_shell_command(raw_value: str) -> bool:
    return any(char in raw_value for char in _SHELL_META_CHARS) or "$" in raw_value


__all__ = [
    "EditorResolution",
    "resolve_editor",
]
