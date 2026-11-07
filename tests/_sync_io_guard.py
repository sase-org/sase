"""Caller-scoped guard proving that code under test does no synchronous file I/O.

Tests that pin a hot path to memory used to monkeypatch ``os.stat``,
``pathlib.Path.exists``, ``builtins.open`` and friends process-wide with a stub
that raises. Those names are shared with the harness running the test.
Coverage's C tracer calls ``os.path.exists`` (and so ``os.stat``) from inside
traced code whenever ``sys.path`` changed since the last new file it saw, and
pytest's failure reporting calls ``os.stat`` (via ``linecache``) and
``Path.exists``. A stub raising there kills the xdist worker with an
INTERNALERROR (CI Telemetry's ``coverage-contexts`` lane died that way) or turns
the guarded test's own failure into one.

:func:`forbid_sync_file_io` patches the same names, but only for the ``with``
block, by default only on the calling thread, and only for calls whose nearest
attributable frame belongs to the code under test (the ``sase`` package). A
call that reaches a patched name through coverage, pytest, pluggy, xdist, or
execnet first goes to the real function. An in-scope call is recorded and
raises :class:`ForbiddenFileIO`. If anything was recorded, the block also fails
on exit, so code that swallows the error still fails the test.
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import os
import threading
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from types import FrameType
from typing import Any

import pytest

_HARNESS_PACKAGES = (
    "_pytest",
    "coverage",
    "execnet",
    "pluggy",
    "pytest",
    "pytest_cov",
    "xdist",
)
_MAX_ARG_REPR = 120


def _package_dirs(name: str) -> tuple[str, ...]:
    """Return ``name``'s package directories, each ending in a separator."""
    spec = importlib.util.find_spec(name)
    if spec is None or not spec.submodule_search_locations:
        return ()
    dirs: list[str] = []
    for location in spec.submodule_search_locations:
        for variant in (os.path.abspath(location), os.path.realpath(location)):
            prefix = os.path.join(variant, "")
            if prefix not in dirs:
                dirs.append(prefix)
    return tuple(dirs)


#: Directories whose frames count as the code under test.
CODE_UNDER_TEST_DIRS = _package_dirs("sase")
#: Directories whose frames mark a call as the harness's own, never the test's.
HARNESS_DIRS = tuple(
    prefix for package in _HARNESS_PACKAGES for prefix in _package_dirs(package)
)


class ForbiddenFileIO(AssertionError):
    """Raised when code under test performs I/O a guard forbids."""


@dataclass(frozen=True)
class FileIOCall:
    """One forbidden call: the patched target, its arguments, and the caller."""

    target: str
    args: tuple[object, ...]
    site: str

    def describe(self) -> str:
        rendered = ", ".join(_short_repr(arg) for arg in self.args)
        return f"{self.target}({rendered}) from {self.site}"


@dataclass
class SyncFileIOGuard:
    """One :func:`forbid_sync_file_io` block's scope and recorded calls."""

    reason: str
    code_under_test: tuple[str, ...]
    owner_thread: int | None
    calls: list[FileIOCall] = field(default_factory=list)


@contextmanager
def forbid_sync_file_io(
    *targets: str,
    reason: str,
    any_thread: bool = False,
    code_under_test: tuple[str, ...] = CODE_UNDER_TEST_DIRS,
) -> Generator[SyncFileIOGuard]:
    """Fail if code under test calls any dotted ``targets`` inside the block.

    ``targets`` are importable dotted names such as ``"os.stat"``,
    ``"pathlib.Path.exists"``, or ``"builtins.open"``. ``reason`` leads every
    failure message. ``any_thread`` widens the guard from the calling thread to
    every thread, for tests whose code under test may hop threads.
    ``code_under_test`` holds directory prefixes (each ending in a separator)
    whose frames count as the code under test; it defaults to the ``sase``
    package.
    """
    if not targets:
        raise ValueError("forbid_sync_file_io needs at least one target")
    guard = SyncFileIOGuard(
        reason=reason,
        code_under_test=code_under_test,
        owner_thread=None if any_thread else threading.get_ident(),
    )
    with pytest.MonkeyPatch.context() as patcher:
        for target in targets:
            owner, attr = _resolve(target)
            original = getattr(owner, attr)
            patcher.setattr(owner, attr, _guarded(target, original, guard))
        yield guard
    if guard.calls:
        details = "\n  ".join(call.describe() for call in guard.calls)
        raise AssertionError(f"{reason}:\n  {details}")


def _guarded(
    target: str, original: Callable[..., Any], guard: SyncFileIOGuard
) -> Callable[..., Any]:
    def guarded(*args: Any, **kwargs: Any) -> Any:
        if guard.owner_thread in (None, threading.get_ident()):
            current = inspect.currentframe()
            caller = current.f_back if current else None
            del current
            site = _code_under_test_site(caller, guard.code_under_test)
            del caller
            if site is not None:
                call = FileIOCall(target, args, site)
                guard.calls.append(call)
                raise ForbiddenFileIO(f"{guard.reason}: {call.describe()}")
        return original(*args, **kwargs)

    return guarded


def _code_under_test_site(
    frame: FrameType | None, code_under_test: tuple[str, ...]
) -> str | None:
    """Describe the nearest code-under-test frame, unless the harness is nearer.

    Stdlib, third-party, and test frames are neither: walking past them keeps
    ``sase -> library -> os.stat`` attributable to sase, while coverage's
    tracer and pytest's reporting stop the walk before any sase frame below.
    Never touches the filesystem: ``linecache`` would re-enter the guard.
    """
    while frame is not None:
        filename = frame.f_code.co_filename
        if filename.startswith(HARNESS_DIRS):
            return None
        for prefix in code_under_test:
            if filename.startswith(prefix):
                package = os.path.basename(os.path.dirname(prefix))
                relative = filename[len(prefix) :]
                return (
                    f"{package}/{relative}:{frame.f_lineno} in {frame.f_code.co_name}"
                )
        frame = frame.f_back
    return None


def _resolve(target: str) -> tuple[object, str]:
    """Return ``(owner, attribute)`` for an importable dotted ``target``."""
    owner_path, _, attr = target.rpartition(".")
    parts = owner_path.split(".")
    for split in range(len(parts), 0, -1):
        try:
            owner: object = importlib.import_module(".".join(parts[:split]))
        except ImportError:
            continue
        for part in parts[split:]:
            owner = getattr(owner, part)
        break
    else:
        raise ValueError(f"cannot import an owner for {target!r}")
    static = inspect.getattr_static(owner, attr)
    if isinstance(static, (classmethod, staticmethod)):
        raise TypeError(f"{target!r} is a {type(static).__name__}; guard its callee")
    return owner, attr


def _short_repr(value: object) -> str:
    text = repr(value)
    if len(text) <= _MAX_ARG_REPR:
        return text
    return text[: _MAX_ARG_REPR - 3] + "..."
