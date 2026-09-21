"""The single subprocess boundary: run ``uv`` and parse its output.

Everything else in :mod:`sase.uv_tool` is pure; this module is the only place
that shells out. It follows the repo's runner conventions (an argv list,
``check=False`` capture with a timeout, ``FileNotFoundError`` mapped to a typed
error) and parses uv's human output into a structured :class:`UvChangeSet`.

uv writes its resolution log to **stderr** as ``+ pkg==X`` / ``- pkg==Y`` lines
(plus ``Resolved`` / ``Installed`` / ``Uninstalled`` summaries); a no-op prints
``... is already installed`` or ``Nothing to upgrade``. A package appearing in
both ``-`` and ``+`` is an upgrade (``old -> new``).
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum

from sase.uv_tool.errors import UvCommandFailedError, UvNotFoundError
from sase.version._utils import normalize_distribution_name

#: Generous default: an install/upgrade may download and build packages.
UV_TIMEOUT_SECONDS = 300.0

#: ``[+-] name==version`` change line (the version stops at the first space, so a
#: trailing `` (from git+...)`` source annotation is ignored).
_CHANGE_RE = re.compile(
    r"^\s*(?P<sign>[+\-])\s+(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>\S+)"
)

RunFn = Callable[..., "subprocess.CompletedProcess[str]"]


class ChangeKind(Enum):
    """How one package changed across a ``uv`` run."""

    ADDED = "added"
    REMOVED = "removed"
    UPGRADED = "upgraded"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class UvPackageChange:
    """A single package's change: ``old_version`` / ``new_version`` per kind."""

    name: str
    kind: ChangeKind
    old_version: str | None = None
    new_version: str | None = None


@dataclass(frozen=True)
class UvChangeSet:
    """The parsed result of a ``uv`` run, in first-appearance order."""

    changes: tuple[UvPackageChange, ...] = ()
    raw_output: str = ""

    @property
    def is_noop(self) -> bool:
        """Whether uv reported no package changes."""
        return not self.changes

    def by_kind(self, kind: ChangeKind) -> tuple[UvPackageChange, ...]:
        """All changes of the given *kind*."""
        return tuple(change for change in self.changes if change.kind is kind)

    @property
    def added(self) -> tuple[UvPackageChange, ...]:
        return self.by_kind(ChangeKind.ADDED)

    @property
    def removed(self) -> tuple[UvPackageChange, ...]:
        return self.by_kind(ChangeKind.REMOVED)

    @property
    def upgraded(self) -> tuple[UvPackageChange, ...]:
        return self.by_kind(ChangeKind.UPGRADED)

    def get(self, name: str) -> UvPackageChange | None:
        """Return the change for *name* (normalized match), or ``None``."""
        key = normalize_distribution_name(name)
        for change in self.changes:
            if normalize_distribution_name(change.name) == key:
                return change
        return None


def match_uv_change_line(line: str) -> tuple[str, str, str] | None:
    """Match one ``[+-] name==version`` uv output line.

    Return ``(sign, name, version)`` where *sign* is ``"+"`` or ``"-"``,
    or ``None`` when the line is not a package change line. This is the
    public face of :data:`_CHANGE_RE` for live-progress line watchers that
    turn streamed ``+``/``-`` rows into per-package timeline children.
    """
    match = _CHANGE_RE.match(line)
    if match is None:
        return None
    return (match.group("sign"), match.group("name"), match.group("version"))


def parse_uv_output(output: str) -> UvChangeSet:
    """Parse uv's stdout/stderr text into a :class:`UvChangeSet`.

    Pure: classifies each package as added (only ``+``), removed (only ``-``), or
    upgraded (both, ``old -> new``), preserving first-appearance order.
    """
    added: dict[str, tuple[str, str]] = {}
    removed: dict[str, tuple[str, str]] = {}
    order: list[str] = []
    seen: set[str] = set()

    for line in output.splitlines():
        match = _CHANGE_RE.match(line)
        if match is None:
            continue
        name = match.group("name")
        version = match.group("version")
        key = normalize_distribution_name(name)
        target = added if match.group("sign") == "+" else removed
        target[key] = (name, version)
        if key not in seen:
            seen.add(key)
            order.append(key)

    changes = tuple(_classify(key, added, removed) for key in order)
    return UvChangeSet(changes=changes, raw_output=output)


def run_uv(
    argv: Sequence[str],
    *,
    run_fn: RunFn = subprocess.run,
    timeout: float = UV_TIMEOUT_SECONDS,
    on_output: Callable[[str, str], None] | None = None,
) -> UvChangeSet:
    """Execute *argv* (a ``uv ...`` command) and return its parsed change set.

    Raises :class:`~sase.uv_tool.errors.UvNotFoundError` when ``uv`` is missing
    and :class:`~sase.uv_tool.errors.UvCommandFailedError` on timeout, OS error,
    or a non-zero exit.

    A non-``None`` ``on_output`` streams each output line through the
    line-streaming runner; ``None`` keeps the legacy ``run_fn`` capture path.
    """
    args = list(argv)
    if on_output is not None:
        from sase.dev_update.stream_command import run_streaming

        try:
            result = run_streaming(args, timeout=timeout, on_line=on_output)
        except FileNotFoundError as exc:
            raise UvNotFoundError() from exc
        except subprocess.TimeoutExpired as exc:
            raise UvCommandFailedError(argv=args, timeout=timeout) from exc
        except (OSError, subprocess.SubprocessError) as exc:
            raise UvCommandFailedError(
                argv=args, stderr=f"{type(exc).__name__}: {exc}"
            ) from exc

        if result.returncode != 0:
            raise UvCommandFailedError(
                argv=args,
                returncode=result.returncode,
                stderr=result.stderr,
                stdout=result.stdout,
            )

        return parse_uv_output(_combined_output(result))
    try:
        result = run_fn(args, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise UvNotFoundError() from exc
    except subprocess.TimeoutExpired as exc:
        raise UvCommandFailedError(argv=args, timeout=timeout) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise UvCommandFailedError(
            argv=args, stderr=f"{type(exc).__name__}: {exc}"
        ) from exc

    if result.returncode != 0:
        raise UvCommandFailedError(
            argv=args,
            returncode=result.returncode,
            stderr=result.stderr,
            stdout=result.stdout,
        )

    return parse_uv_output(_combined_output(result))


def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
    parts = [text for text in (result.stderr, result.stdout) if text]
    return "\n".join(parts)


def _classify(
    key: str,
    added: dict[str, tuple[str, str]],
    removed: dict[str, tuple[str, str]],
) -> UvPackageChange:
    add_entry = added.get(key)
    remove_entry = removed.get(key)
    if add_entry is not None and remove_entry is not None:
        return UvPackageChange(
            name=add_entry[0],
            kind=ChangeKind.UPGRADED,
            old_version=remove_entry[1],
            new_version=add_entry[1],
        )
    if add_entry is not None:
        return UvPackageChange(
            name=add_entry[0],
            kind=ChangeKind.ADDED,
            new_version=add_entry[1],
        )
    # remove_entry is not None here (key came from the union).
    assert remove_entry is not None
    return UvPackageChange(
        name=remove_entry[0],
        kind=ChangeKind.REMOVED,
        old_version=remove_entry[1],
    )


__all__ = [
    "UV_TIMEOUT_SECONDS",
    "ChangeKind",
    "UvChangeSet",
    "UvPackageChange",
    "match_uv_change_line",
    "parse_uv_output",
    "run_uv",
]
