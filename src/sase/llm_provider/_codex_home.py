"""Codex home isolation and shadow-home helpers."""

from __future__ import annotations

import os
import shutil
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sase.env_contracts import SASE_ACTIVE_PROJECT_DIR_ENV

from ._codex_instructions import explicit_instructions_enabled
from .instruction_delivery import sase_owned_instruction_paths

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
        "sessions",
        "skills",
        "version.json",
    }
)
CODEX_SHADOW_HOME_LEGACY_ENTRIES = frozenset({"memories"})
WORKSPACE_ENV_VARS: tuple[str, ...] = ("SASE_GIT_WORKSPACE_DIR",)


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


def _create_shadow_codex_home(real_home: Path) -> Path:
    """Create an allowlisted disposable CODEX_HOME without shared sqlite state."""
    cache_root = _sase_codex_shadow_home_root()
    cache_root.mkdir(parents=True, exist_ok=True)

    shadow_home = cache_root / f"{os.getpid()}-{uuid.uuid4().hex}"
    shadow_home.mkdir(mode=0o700)

    explicit = explicit_instructions_enabled()
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
    return shadow_home


@contextmanager
def codex_subprocess_env() -> Iterator[dict[str, str]]:
    """Yield an env for Codex, isolating config writes unless disabled."""
    if os.environ.get(DISABLE_SHADOW_HOME_ENV) == "1":
        env = os.environ.copy()
        env["CODEX_PROJECT_DIR"] = resolve_codex_project_dir()
        yield env
        return

    shadow_home = _create_shadow_codex_home(real_codex_home())
    env = os.environ.copy()
    env["CODEX_HOME"] = str(shadow_home)
    env["CODEX_PROJECT_DIR"] = resolve_codex_project_dir()
    try:
        yield env
    finally:
        shutil.rmtree(shadow_home, ignore_errors=True)


__all__ = [
    "codex_subprocess_env",
    "is_sase_managed_codex_home",
    "real_codex_home",
    "resolve_codex_project_dir",
]
