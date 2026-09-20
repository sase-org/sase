"""Stable executable resolution for long-lived service hosts."""

from __future__ import annotations

import functools
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable, Iterable, Mapping

from sase.service.config import ServiceProcConfig, load_service_config


@dataclass(frozen=True)
class StableExecutable:
    """Resolved long-lived ``sase`` executable and its drift diagnostics."""

    path: Path | None
    diagnostics: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        return self.path is not None


def resolve_stable_sase_executable(
    *,
    resolver: Callable[[], str | None] | None = None,
) -> StableExecutable:
    """Resolve the stable ``sase`` executable used by platform service units."""
    if resolver is not None:
        resolved = resolver()
    else:
        resolved = _canonical_axe_start_command()
    if not resolved:
        return StableExecutable(
            path=None,
            diagnostics=(
                "could not find a stable non-ephemeral `sase` executable; "
                "install SASE into a durable environment before running `sase service init`",
            ),
        )
    path = Path(str(resolved)).expanduser()
    if not path.exists():
        return StableExecutable(
            path=None,
            diagnostics=(f"stable `sase` executable is missing: {path}",),
        )
    return StableExecutable(path=path.resolve(strict=False))


@dataclass(frozen=True)
class ResolvedLauncherArgv:
    """A launcher argv after bare-name resolution, plus why it may not resolve."""

    argv: tuple[str, ...]
    diagnostic: str | None = None


def resolve_launcher_argv(
    argv: tuple[str, ...],
    *,
    which_fn: Callable[[str], str | None] = shutil.which,
    interpreter: str | None = None,
) -> ResolvedLauncherArgv:
    """Resolve a bare ``argv[0]`` on ``PATH``, then next to the interpreter.

    ``uv tool install --with`` links only the primary package's entry points
    onto ``PATH``; a plugin's console scripts live solely in the tool venv's
    bin directory, which is where the running interpreter sits. ``PATH`` wins
    so every launcher that resolves today keeps resolving to the same file. An
    ``argv[0]`` that already names a path, and every later argument, pass
    through untouched. When nothing resolves, ``argv`` is returned unchanged
    with a diagnostic explaining the miss.
    """
    if not argv or _is_explicit_path(argv[0]):
        return ResolvedLauncherArgv(argv)
    name = argv[0]
    on_path = which_fn(name)
    if on_path:
        return ResolvedLauncherArgv(argv)
    bin_dir = Path(sys.executable if interpreter is None else interpreter).parent
    sibling = bin_dir / name
    if sibling.is_file() and os.access(sibling, os.X_OK):
        return ResolvedLauncherArgv((str(sibling), *argv[1:]))
    return ResolvedLauncherArgv(
        argv,
        diagnostic=(
            f"`{name}` was not found on PATH or in {bin_dir}; `uv tool install "
            "--with` does not link a plugin's console scripts onto PATH, so "
            "install the plugin into the same environment as `sase` or give the "
            "launcher an absolute path"
        ),
    )


def service_launcher_warnings(
    env: Mapping[str, str],
    *,
    procs: Iterable[ServiceProcConfig] | None = None,
    interpreter: str | None = None,
) -> tuple[str, ...]:
    """Warn for each enabled command proc whose launcher resolves nowhere.

    Names are resolved against ``env``'s ``PATH`` (the one the host will
    capture), then next to ``interpreter``. Readiness reporting is advisory, so
    an unreadable service config yields no warnings instead of failing
    ``sase service init``.
    """
    if procs is None:
        try:
            procs = load_service_config().procs
        except Exception:  # noqa: BLE001 - advisory only.
            return ()
    which_fn = functools.partial(shutil.which, path=env.get("PATH"))
    warnings: list[str] = []
    for proc in procs:
        launcher = proc.launcher
        if not (proc.available and proc.enabled) or launcher is None:
            continue
        # An entry that sets its own PATH cannot be judged against the captured one.
        if launcher.kind != "command" or "PATH" in proc.env:
            continue
        diagnostic = resolve_launcher_argv(
            launcher.argv, which_fn=which_fn, interpreter=interpreter
        ).diagnostic
        if diagnostic is not None:
            warnings.append(f"service proc `{proc.name}` cannot start: {diagnostic}")
    return tuple(warnings)


def _is_explicit_path(name: str) -> bool:
    return os.sep in name or (os.altsep is not None and os.altsep in name)


def _canonical_axe_start_command() -> str | None:
    """Use the existing AXE canonical-start resolver as the shared source."""
    try:
        from sase.axe.process import canonical_axe_start_command

        return canonical_axe_start_command()
    except Exception:
        return None


__all__ = [
    "ResolvedLauncherArgv",
    "StableExecutable",
    "resolve_launcher_argv",
    "resolve_stable_sase_executable",
    "service_launcher_warnings",
]
