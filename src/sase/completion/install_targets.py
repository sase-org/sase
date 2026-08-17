"""Shell detection and completion-script target resolution."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


SUPPORTED_SHELLS: tuple[str, ...] = ("bash", "fish", "zsh")

SCRIPT_NAMES: dict[str, str] = {
    "bash": "sase",
    "fish": "sase.fish",
    "zsh": "_sase",
}

ZSH_PROBE_TIMEOUT_SECONDS = 5.0

_SHELL_BASENAMES: dict[str, str] = {
    "bash": "bash",
    "-bash": "bash",
    "fish": "fish",
    "-fish": "fish",
    "zsh": "zsh",
    "-zsh": "zsh",
}


class CompletionInstallError(Exception):
    """User-facing failure while installing shell completion."""


class CannotDetectShell(CompletionInstallError):
    """Neither ``$SHELL`` nor the parent process named a supported shell."""


class ForeignInstallError(CompletionInstallError):
    """The target file exists and was not written by sase."""


@dataclass(frozen=True, slots=True)
class DetectedShell:
    """A resolved install shell plus the evidence used to pick it."""

    name: str
    source: str
    shell_env: str | None
    parent: str | None


@dataclass(frozen=True, slots=True)
class TargetChoice:
    """The directory chosen for a completion script."""

    directory: Path
    reason: str


def _script_filename(shell: str) -> str:
    """Return the compsys / bash-completion / fish filename for *shell*."""
    try:
        return SCRIPT_NAMES[shell]
    except KeyError as exc:
        raise CompletionInstallError(f"unsupported shell: {shell}") from exc


def script_path(directory: Path, shell: str) -> Path:
    """Return the full script path for *shell* inside *directory*."""
    return directory / _script_filename(shell)


def _normalize_shell_name(value: str) -> str | None:
    """Map a ``$SHELL`` path or process comm name onto a supported shell."""
    return _SHELL_BASENAMES.get(Path(value).name)


def _read_parent_comm(*, ppid: int | None = None) -> str | None:
    """Return the parent process comm name, or ``None`` when unreadable."""
    pid = os.getppid() if ppid is None else ppid
    try:
        return Path(f"/proc/{pid}/comm").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def detect_shell(
    *,
    requested: str | None = None,
    environ: Mapping[str, str] | None = None,
    parent: str | None | object = ...,
) -> DetectedShell:
    """Detect the install shell from an explicit value, ``$SHELL``, or ppid.

    Never guesses silently: the returned ``source`` always names the evidence.
    """
    env = os.environ if environ is None else environ
    shell_env = env.get("SHELL")
    parent_comm = _read_parent_comm() if parent is ... else parent
    parent_name = str(parent_comm) if parent_comm else None

    if requested:
        normalized = _normalize_shell_name(requested) or (
            requested if requested in SUPPORTED_SHELLS else None
        )
        if normalized is None:
            raise CompletionInstallError(f"unsupported shell: {requested}")
        return DetectedShell(
            name=normalized,
            source="explicit",
            shell_env=shell_env,
            parent=parent_name,
        )

    parent_shell = _normalize_shell_name(parent_name) if parent_name else None
    if parent_shell is not None:
        return DetectedShell(
            name=parent_shell,
            source=f"parent process {parent_name!r}",
            shell_env=shell_env,
            parent=parent_name,
        )

    env_shell = _normalize_shell_name(shell_env) if shell_env else None
    if env_shell is not None:
        return DetectedShell(
            name=env_shell,
            source=f"$SHELL={shell_env}",
            shell_env=shell_env,
            parent=parent_name,
        )

    raise CannotDetectShell(
        "could not detect a supported shell from $SHELL or the parent "
        "process; pass bash, fish, or zsh"
    )


def _conventional_dir(
    shell: str,
    *,
    home: Path,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Return the conventional user directory for *shell*."""
    env = {} if environ is None else environ
    if shell == "bash":
        xdg = env.get("XDG_DATA_HOME")
        base = Path(xdg).expanduser() if xdg else home / ".local" / "share"
        return base / "bash-completion" / "completions"
    if shell == "fish":
        xdg = env.get("XDG_CONFIG_HOME")
        base = Path(xdg).expanduser() if xdg else home / ".config"
        return base / "fish" / "completions"
    if shell == "zsh":
        return home / ".zfunc"
    raise CompletionInstallError(f"unsupported shell: {shell}")


def _dir_is_writable(path: Path) -> bool:
    """Return whether *path* exists as a writable directory."""
    try:
        return path.is_dir() and os.access(path, os.W_OK | os.X_OK)
    except OSError:
        return False


# Shell frameworks put every enabled plugin's own directory on ``fpath``, and
# those directories are writable by whoever installed the framework -- on an
# oh-my-zsh host the first scanned entry is some unrelated plugin's checkout.
# Dropping ``_sase`` in there hijacks another project's tree and silently
# unloads sase completion the day that plugin is disabled. Frameworks all
# publish a drop-in directory named ``completions`` for exactly this purpose,
# so inside a framework tree that name is the only acceptable target.
_FRAMEWORK_DIR_NAMES: frozenset[str] = frozenset(
    {
        "antidote",
        "antigen",
        "bash-it",
        "oh-my-bash",
        "oh-my-fish",
        "oh-my-zsh",
        "omf",
        "prezto",
        "sheldon",
        "zgen",
        "zgenom",
        "zim",
        "zinit",
        "znap",
        "zplug",
        "zprezto",
    }
)
_DROP_IN_DIR_NAME = "completions"


def _cache_managed(parts: tuple[str, ...], environ: Mapping[str, str]) -> bool:
    """Return whether *parts* names a path inside a cache root."""
    if ".cache" in parts:
        return True
    xdg_cache = environ.get("XDG_CACHE_HOME", "").strip()
    if not xdg_cache:
        return False
    cache_parts = Path(xdg_cache).expanduser().parts
    return parts[: len(cache_parts)] == cache_parts


def _is_framework_drop_in(path: Path, *, environ: Mapping[str, str]) -> bool:
    """Return whether *path* is a framework's third-party drop-in directory."""
    if _cache_managed(tuple(path.parts), environ):
        return False
    parts = tuple(part.lstrip(".") for part in path.parts)
    return not _FRAMEWORK_DIR_NAMES.isdisjoint(parts) and path.name == _DROP_IN_DIR_NAME


def _is_acceptable_target(path: Path, *, environ: Mapping[str, str]) -> bool:
    """Return whether a scanned *path* is a sane place to install a script.

    Framework plugin directories and cache roots are scanned and writable but
    belong to something else; a framework's ``completions`` drop-in directory
    is the one exception, since publishing third-party scripts is what it is
    for.
    """
    parts = tuple(part.lstrip(".") for part in path.parts)
    if _cache_managed(tuple(path.parts), environ):
        return False
    if not _FRAMEWORK_DIR_NAMES.isdisjoint(parts):
        return path.name == _DROP_IN_DIR_NAME
    return True


def _drop_in_rank(path: Path) -> int:
    """Rank drop-in directories, preferring a framework's user-owned area.

    oh-my-zsh's ``$ZSH_CUSTOM`` (``~/.oh-my-zsh/custom``) is the tree it tells
    users to put their own files in and the one its updater leaves alone, so a
    ``custom`` component wins over the framework's own checkout.
    """
    return 0 if "custom" in (part.lstrip(".") for part in path.parts) else 1


def _under_home(path: Path, home: Path) -> bool:
    """Return whether *path* lives inside *home*, without touching the disk."""
    try:
        return path.expanduser().is_relative_to(home.expanduser())
    except (OSError, ValueError):
        return False


def _probe_zsh_fpath(
    *,
    timeout: float = ZSH_PROBE_TIMEOUT_SECONDS,
    env: Mapping[str, str] | None = None,
    zsh: str | None = None,
) -> tuple[Path, ...]:
    """Return the user's interactive zsh ``fpath``, or empty on failure."""
    binary = zsh or shutil.which("zsh")
    if binary is None:
        return ()
    try:
        completed = subprocess.run(
            [binary, "-ic", "print -rl -- $fpath"],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=None if env is None else dict(env),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ()
    return tuple(
        Path(line).expanduser()
        for line in completed.stdout.splitlines()
        if line.strip()
    )


def probe_zsh_comps(
    *,
    timeout: float = ZSH_PROBE_TIMEOUT_SECONDS,
    env: Mapping[str, str] | None = None,
    zsh: str | None = None,
) -> str | None:
    """Return ``_comps[sase]`` from an interactive zsh, or ``None`` on failure.

    A successful probe that finds no registration returns the literal
    ``UNSET``. File presence is not evidence of a working install.
    """
    binary = zsh or shutil.which("zsh")
    if binary is None:
        return None
    try:
        completed = subprocess.run(
            [binary, "-ic", "print -r -- ${_comps[sase]:-UNSET}"],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=None if env is None else dict(env),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = completed.stdout.strip()
    return value or None


def _default_scanned_dirs(
    shell: str,
    *,
    home: Path,
    environ: Mapping[str, str] | None = None,
    fpath: Sequence[Path] | None = None,
) -> tuple[Path, ...]:
    """Return directories the *shell* actually scans for completion scripts."""
    env = os.environ if environ is None else environ
    if shell == "zsh":
        if fpath is not None:
            return tuple(Path(item) for item in fpath)
        return _probe_zsh_fpath(env=env)
    if shell == "bash":
        return (
            _conventional_dir("bash", home=home, environ=env),
            Path("/usr/share/bash-completion/completions"),
        )
    if shell == "fish":
        return (
            _conventional_dir("fish", home=home, environ=env),
            Path("/usr/share/fish/vendor_completions.d"),
        )
    raise CompletionInstallError(f"unsupported shell: {shell}")


def resolve_target(
    shell: str,
    *,
    target: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    scanned: Sequence[Path] | None = None,
    writable: Callable[[Path], bool] | None = None,
) -> TargetChoice:
    """Choose the install directory using the documented priority order.

    1. ``-t/--target``
    2. ``SASE_COMPLETION_DIR``
    3. the first writable scanned directory that is not owned by a shell
       framework or a cache, preferring one under the user's home
    4. the conventional user directory
    """
    if shell not in SUPPORTED_SHELLS:
        raise CompletionInstallError(f"unsupported shell: {shell}")
    env = os.environ if environ is None else environ
    home_path = Path.home() if home is None else home
    writable_fn = _dir_is_writable if writable is None else writable

    if target is not None:
        return TargetChoice(Path(target).expanduser(), "--target")

    env_dir = env.get("SASE_COMPLETION_DIR")
    if env_dir:
        return TargetChoice(Path(env_dir).expanduser(), "SASE_COMPLETION_DIR")

    scanned_dirs = (
        tuple(Path(item) for item in scanned)
        if scanned is not None
        else _default_scanned_dirs(shell, home=home_path, environ=env)
    )
    # A framework's drop-in directory is the only scanned entry whose ordering
    # is guaranteed: the framework puts it on `fpath` itself, before it runs
    # `compinit`. A plain user directory such as `~/.zfunc` is often appended
    # *after* `compinit`, where a script in it is a silent no-op -- and the
    # fpath probe cannot tell the two apart, since it reads `fpath` once rc
    # processing has finished. So prefer the drop-in, creating it when the
    # framework ships the fpath entry without the directory.
    drop_ins = sorted(
        (
            directory
            for directory in scanned_dirs
            if _is_framework_drop_in(directory, environ=env)
            and (writable_fn(directory) or writable_fn(directory.parent))
        ),
        key=_drop_in_rank,
    )
    if drop_ins:
        return TargetChoice(drop_ins[0], "framework completions directory")

    usable = [
        directory
        for directory in scanned_dirs
        if writable_fn(directory) and _is_acceptable_target(directory, environ=env)
    ]
    for directory in usable:
        if _under_home(directory, home_path):
            return TargetChoice(directory, "scanned directory")
    if usable:
        return TargetChoice(usable[0], "scanned directory")

    return TargetChoice(
        _conventional_dir(shell, home=home_path, environ=env),
        "conventional directory",
    )


def fpath_hint_line(directory: Path, *, home: Path | None = None) -> str:
    """Return the copy-pasteable ``fpath`` line that must precede ``compinit``."""
    home_path = Path.home() if home is None else home
    display = _display_path(directory, home_path)
    return f"fpath=({display} $fpath)   # must appear BEFORE compinit"


def _display_path(path: Path, home: Path) -> str:
    try:
        return f"~/{path.resolve().relative_to(home.resolve()).as_posix()}"
    except (OSError, ValueError):
        return str(path)


__all__ = [
    "CannotDetectShell",
    "CompletionInstallError",
    "DetectedShell",
    "ForeignInstallError",
    "SUPPORTED_SHELLS",
    "TargetChoice",
    "ZSH_PROBE_TIMEOUT_SECONDS",
    "detect_shell",
    "fpath_hint_line",
    "probe_zsh_comps",
    "resolve_target",
    "script_path",
]
