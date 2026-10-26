"""Codex home isolation and shadow-home helpers."""

from __future__ import annotations

import errno
import logging
import os
import shutil
import stat
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

from sase.env_contracts import SASE_ACTIVE_PROJECT_DIR_ENV

from .instruction_delivery import (
    current_instruction_delivery,
    sase_owned_instruction_paths,
)

DISABLE_SHADOW_HOME_ENV = "SASE_CODEX_DISABLE_SHADOW_HOME"
CODEX_SHADOW_HOME_SYMLINK_ENTRIES = frozenset(
    {
        "AGENTS.md",
        "AGENTS.override.md",
        "auth.json",
        "cache",
        "hooks.json",
        "installation_id",
        "models_cache.json",
        "plugins",
        "skills",
        "version.json",
    }
)
CODEX_SHADOW_HOME_LEGACY_ENTRIES = frozenset({"memories"})
WORKSPACE_ENV_VARS: tuple[str, ...] = ("SASE_GIT_WORKSPACE_DIR",)
ORPHAN_SHADOW_HOME_MAX_AGE_SECONDS = 60 * 60
_ORPHAN_SWEEP_MAX_DIRS = 256
_COPY_CHUNK_SIZE = 1024 * 1024

log = logging.getLogger(__name__)


def _sase_codex_shadow_home_root() -> Path:
    """Return the root directory for SASE-managed Codex shadow homes."""
    return (Path.home() / ".cache" / "sase" / "codex_home").resolve(strict=False)


def is_sase_managed_codex_home(path: str | os.PathLike[str]) -> bool:
    """Return whether *path* points inside SASE's Codex shadow-home root."""
    candidate = Path(path).expanduser().resolve(strict=False)
    root = _sase_codex_shadow_home_root()
    return candidate == root or candidate.is_relative_to(root)


def _workspace_env_value() -> str | None:
    """Return the first non-empty SASE workspace env var value, if any."""
    for name in WORKSPACE_ENV_VARS:
        value = os.environ.get(name)
        if value:
            return value
    return None


def resolve_codex_project_dir() -> str:
    """Resolve the project directory Codex hooks and fallbacks should inspect."""
    return (
        os.environ.get("CODEX_PROJECT_DIR")
        or os.environ.get(SASE_ACTIVE_PROJECT_DIR_ENV)
        or _workspace_env_value()
        or os.getcwd()
    )


def real_codex_home() -> Path:
    """Return the user's real Codex home (never a per-run shadow home)."""
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home and not is_sase_managed_codex_home(codex_home):
        return Path(codex_home).expanduser().resolve(strict=False)
    return Path.home() / ".codex"


def active_explicit_codex_delivery() -> bool:
    """Return whether this invocation has an active explicit Codex root.

    True only when the bound delivery is Codex, the root slot is
    ``explicit``, and the root text is non-empty — the same condition
    ``CodexProvider.invoke`` uses for developer-instruction text.
    """
    delivery = current_instruction_delivery()
    return (
        delivery is not None
        and delivery.provider == "codex"
        and delivery.root.plan.status == "explicit"
        and bool(delivery.root.text)
    )


def _path_exists_or_is_symlink(path: Path) -> bool:
    """Return whether a path exists or is present as a symlink."""
    return path.exists() or path.is_symlink()


def _link_home_agents_fallback(shadow_home: Path, real_home: Path) -> None:
    """Expose SASE's home AGENTS.md to Codex when no Codex-global file wins."""
    home_agents = Path.home() / "AGENTS.md"
    shadow_agents = shadow_home / "AGENTS.md"

    if not home_agents.exists():
        return
    if _path_exists_or_is_symlink(shadow_agents):
        return
    if _path_exists_or_is_symlink(real_home / "AGENTS.override.md"):
        return
    if _path_exists_or_is_symlink(shadow_home / "AGENTS.override.md"):
        return

    shadow_agents.symlink_to(home_agents)


def _is_sase_owned_instruction_file(path: Path, owned_paths: tuple[Path, ...]) -> bool:
    """Return whether a Codex home instruction file points to or copies SASE text."""
    resolved_owned_paths = {owned.resolve(strict=False) for owned in owned_paths}
    if path.is_symlink() and path.resolve(strict=False) in resolved_owned_paths:
        return True
    if not path.is_file():
        return False
    try:
        path_bytes = path.read_bytes()
    except OSError:
        return False
    for owned in owned_paths:
        if not owned.is_file():
            continue
        try:
            if path_bytes == owned.read_bytes():
                return True
        except OSError:
            continue
    return False


def _local_session_dates() -> tuple[date, date]:
    """Return today's and tomorrow's local dates for session day links."""
    today = date.today()
    return today, today + timedelta(days=1)


def _session_day_path(root: Path, day: date) -> Path:
    """Return ``root/YYYY/MM/DD`` for *day*."""
    return root / f"{day.year:04d}" / f"{day.month:02d}" / f"{day.day:02d}"


def _prepare_private_sessions_tree(shadow_home: Path, real_home: Path) -> None:
    """Create a private sessions tree whose today/tomorrow day dirs are real links."""
    sessions = shadow_home / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    real_sessions = real_home / "sessions"
    for day in _local_session_dates():
        real_day = _session_day_path(real_sessions, day)
        shadow_day = _session_day_path(sessions, day)
        try:
            real_day.mkdir(parents=True, exist_ok=True)
            shadow_day.parent.mkdir(parents=True, exist_ok=True)
            if _path_exists_or_is_symlink(shadow_day):
                continue
            shadow_day.symlink_to(real_day, target_is_directory=True)
        except OSError as exc:
            log.warning("Could not link Codex session day %s: %s", real_day, exc)


def _shadow_home_owner_pid(name: str) -> int | None:
    """Return the pid prefix of a shadow-home directory name, if parseable."""
    prefix, sep, rest = name.partition("-")
    if not sep or not rest or not prefix.isdigit():
        return None
    pid = int(prefix)
    if pid <= 1:
        return None
    return pid


def _process_is_gone(pid: int) -> bool:
    """Return whether *pid* is provably not a live process."""
    from sase.ace.hooks.processes import is_process_running

    return not is_process_running(pid)


def _is_old_enough(path: Path) -> bool:
    """Return whether *path*'s mtime is older than the orphan sweep age."""
    try:
        mtime = path.lstat().st_mtime
    except OSError:
        return False
    return time.time() - mtime > ORPHAN_SHADOW_HOME_MAX_AGE_SECONDS


def _copy_fsync_unlink(src: Path, dest: Path) -> bool:
    """Copy *src* to a new *dest*, fsync, then unlink. Never clobber *dest*."""
    try:
        mode = stat.S_IMODE(src.lstat().st_mode)
        fd = os.open(dest, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
    except FileExistsError:
        log.warning("Codex shadow rollout collision at %s; keeping %s", dest, src)
        return False
    except OSError as exc:
        log.warning("Could not copy Codex rollout %s -> %s: %s", src, dest, exc)
        return False
    try:
        with open(src, "rb") as incoming:
            while True:
                chunk = incoming.read(_COPY_CHUNK_SIZE)
                if not chunk:
                    break
                os.write(fd, chunk)
        os.fsync(fd)
    except OSError as exc:
        os.close(fd)
        try:
            dest.unlink()
        except OSError:
            pass
        log.warning("Could not copy Codex rollout %s -> %s: %s", src, dest, exc)
        return False
    os.close(fd)
    try:
        src.unlink()
    except OSError as exc:
        log.warning("Could not unlink rescued Codex rollout %s: %s", src, exc)
        return False
    return True


def _move_regular_file_no_clobber(src: Path, dest: Path) -> bool:
    """Move a regular file without replacing *dest*. Return False to keep the shadow."""
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.warning(
            "Could not create Codex sessions directory %s: %s", dest.parent, exc
        )
        return False
    try:
        os.link(src, dest)
    except OSError as exc:
        if exc.errno == errno.EXDEV:
            return _copy_fsync_unlink(src, dest)
        if exc.errno in {errno.EEXIST, errno.EISDIR}:
            log.warning("Codex shadow rollout collision at %s; keeping %s", dest, src)
            return False
        log.warning("Could not move Codex rollout %s -> %s: %s", src, dest, exc)
        return False
    try:
        src.unlink()
    except OSError as exc:
        log.warning("Could not unlink rescued Codex rollout %s: %s", src, exc)
        return True
    return True


def _iter_stray_session_files(sessions: Path) -> Iterator[Path]:
    """Yield regular files under *sessions* without following directory symlinks."""
    for dirpath, dirnames, filenames in os.walk(
        sessions, topdown=True, followlinks=False
    ):
        current = Path(dirpath)
        kept: list[str] = []
        for name in dirnames:
            child = current / name
            try:
                if child.is_symlink():
                    continue
            except OSError:
                continue
            kept.append(name)
        dirnames[:] = kept
        for name in filenames:
            child = current / name
            try:
                mode = child.lstat().st_mode
            except OSError:
                continue
            if stat.S_ISREG(mode):
                yield child


def _rescue_shadow_sessions(shadow_home: Path, real_home: Path) -> bool:
    """Move stray private-tree rollouts into the real sessions store.

    Returns True when the shadow home may be deleted. A destination collision
    or an uncertain walk leaves the shadow home in place.
    """
    sessions = shadow_home / "sessions"
    try:
        st = sessions.lstat()
    except FileNotFoundError:
        return True
    except OSError as exc:
        log.warning("Could not inspect Codex shadow sessions %s: %s", sessions, exc)
        return False
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        return True

    real_sessions = real_home / "sessions"
    can_delete = True
    try:
        for src in _iter_stray_session_files(sessions):
            dest = real_sessions / src.relative_to(sessions)
            if not _move_regular_file_no_clobber(src, dest):
                can_delete = False
    except OSError as exc:
        log.warning("Could not walk Codex shadow sessions %s: %s", sessions, exc)
        return False
    return can_delete


def _try_delete_shadow_home(shadow_home: Path, real_home: Path) -> None:
    """Rescue stray rollouts, then remove *shadow_home* unless a collision remains."""
    try:
        if not _rescue_shadow_sessions(shadow_home, real_home):
            log.warning(
                "Keeping Codex shadow home %s after sessions rescue collision",
                shadow_home,
            )
            return
        shutil.rmtree(shadow_home, ignore_errors=True)
    except OSError as exc:
        log.warning("Could not remove Codex shadow home %s: %s", shadow_home, exc)


def _is_dir_no_follow(path: Path) -> bool:
    """Return whether *path* is a directory without following a symlink."""
    try:
        return stat.S_ISDIR(path.lstat().st_mode)
    except OSError:
        return False


def _orphan_is_eligible(entry: Path) -> bool:
    """Return whether *entry* is a dead, aged, SASE-managed shadow home."""
    if not _is_dir_no_follow(entry):
        return False
    if not is_sase_managed_codex_home(entry):
        return False
    pid = _shadow_home_owner_pid(entry.name)
    if pid is None:
        return False
    if not _process_is_gone(pid):
        return False
    return _is_old_enough(entry)


def _sweep_orphaned_codex_shadow_homes(cache_root: Path, real_home: Path) -> None:
    """Best-effort rescue and removal of dead, aged SASE shadow homes."""
    try:
        entries = list(cache_root.iterdir())
    except OSError:
        return
    attempted = 0
    for entry in entries:
        try:
            eligible = _orphan_is_eligible(entry)
        except OSError:
            continue
        if not eligible:
            continue
        if attempted >= _ORPHAN_SWEEP_MAX_DIRS:
            break
        attempted += 1
        try:
            _try_delete_shadow_home(entry, real_home)
        except OSError:
            continue


def _create_shadow_codex_home(real_home: Path) -> Path:
    """Create an allowlisted disposable CODEX_HOME without shared sqlite state."""
    cache_root = _sase_codex_shadow_home_root()
    cache_root.mkdir(parents=True, exist_ok=True)
    try:
        _sweep_orphaned_codex_shadow_homes(cache_root, real_home)
    except Exception:  # noqa: BLE001 - orphan sweep must not fail home creation
        log.warning("Codex shadow orphan sweep failed", exc_info=True)

    shadow_home = cache_root / f"{os.getpid()}-{uuid.uuid4().hex}"
    shadow_home.mkdir(mode=0o700)

    explicit = active_explicit_codex_delivery()
    owned_paths = sase_owned_instruction_paths() if explicit else ()
    if real_home.exists():
        for source in real_home.iterdir():
            name = source.name
            if name == "config.toml":
                if source.exists():
                    shutil.copy2(source, shadow_home / name)
                continue
            if name not in CODEX_SHADOW_HOME_SYMLINK_ENTRIES and not (
                name in CODEX_SHADOW_HOME_LEGACY_ENTRIES and not explicit
            ):
                continue
            if (
                explicit
                and name in {"AGENTS.md", "AGENTS.override.md"}
                and _is_sase_owned_instruction_file(source, owned_paths)
            ):
                continue
            if source.exists() or source.is_symlink():
                (shadow_home / name).symlink_to(
                    source, target_is_directory=source.is_dir()
                )

    if not explicit:
        _link_home_agents_fallback(shadow_home, real_home)
    _prepare_private_sessions_tree(shadow_home, real_home)
    return shadow_home


@contextmanager
def codex_subprocess_env() -> Iterator[dict[str, str]]:
    """Yield an env for Codex, isolating config writes unless disabled."""
    if os.environ.get(DISABLE_SHADOW_HOME_ENV) == "1":
        env = os.environ.copy()
        env["CODEX_PROJECT_DIR"] = resolve_codex_project_dir()
        yield env
        return

    real_home = real_codex_home()
    shadow_home = _create_shadow_codex_home(real_home)
    env = os.environ.copy()
    env["CODEX_HOME"] = str(shadow_home)
    env["CODEX_PROJECT_DIR"] = resolve_codex_project_dir()
    try:
        yield env
    finally:
        _try_delete_shadow_home(shadow_home, real_home)


__all__ = [
    "active_explicit_codex_delivery",
    "codex_subprocess_env",
    "is_sase_managed_codex_home",
    "real_codex_home",
    "resolve_codex_project_dir",
]
