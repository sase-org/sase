"""As-seen evidence capture for agent launches.

Records the workspace HEAD and the instruction blob OIDs an agent saw at
launch. All capture is fail-open: any error logs a warning and never blocks
a launch. Blob OIDs use git's blob hashing with no subprocess.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from sase.amd.constants import AGENTS_FILENAME, PROVIDER_SHIM_FILES
from sase.memory.blob_oid import git_blob_oid

logger = logging.getLogger(__name__)

_GIT_TIMEOUT_SECONDS = 10
_LAUNCH_GIT_ENV = {
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_TERMINAL_PROMPT": "0",
}


def _launch_git_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(_LAUNCH_GIT_ENV)
    return env


def capture_workspace_head(workspace_dir: str | Path) -> str | None:
    """Return the project repo HEAD at launch, or None when unavailable."""
    try:
        result = subprocess.run(
            [
                "git",
                "--no-optional-locks",
                "-C",
                str(workspace_dir),
                "rev-parse",
                "HEAD",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
            env=_launch_git_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("launch evidence: workspace HEAD unavailable: %s", exc)
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def _blob_exists_in_repo(repo: Path, oid: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "--no-optional-locks", "-C", str(repo), "cat-file", "-e", oid],
            capture_output=True,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
            env=_launch_git_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _owning_repo(path: Path) -> Path | None:
    try:
        result = subprocess.run(
            [
                "git",
                "--no-optional-locks",
                "-C",
                str(path.parent),
                "rev-parse",
                "--show-toplevel",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
            env=_launch_git_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return Path(result.stdout.strip())


def _is_tracked(repo: Path, path: Path) -> bool:
    try:
        rel = (
            path.resolve(strict=False)
            .relative_to(repo.resolve(strict=False))
            .as_posix()
        )
    except ValueError:
        return False
    try:
        result = subprocess.run(
            [
                "git",
                "--no-optional-locks",
                "-C",
                str(repo),
                "ls-files",
                "--error-unmatch",
                "--",
                rel,
            ],
            capture_output=True,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
            env=_launch_git_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _instruction_snapshot_path(oid: str) -> Path:
    """Return the content-addressed snapshot path for *oid*."""
    return Path.home() / ".sase" / "instruction_snapshots" / oid


def _store_instruction_snapshot_bytes(data: bytes, oid: str | None = None) -> str:
    """Store *data* once under its blob OID; skip when already present."""
    digest = oid or git_blob_oid(data)
    target = _instruction_snapshot_path(digest)
    if target.exists():
        return digest
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
            os.replace(tmp_name, target)
        finally:
            try:
                Path(tmp_name).unlink()
            except FileNotFoundError:
                pass
    except OSError as exc:
        logger.warning("launch evidence: snapshot store failed: %s", exc)
    return digest


def _home_instruction_candidates() -> list[Path]:
    home = Path.home()
    return [home / AGENTS_FILENAME, *(home / name for name in PROVIDER_SHIM_FILES)]


def capture_instruction_snapshot(
    workspace_dir: str | Path,
) -> list[dict[str, Any]]:
    """Capture blob OIDs for the project and home instruction files."""
    from sase.config.core import CHEZMOI_HOME, get_use_chezmoi

    entries: list[dict[str, Any]] = []
    workspace = Path(workspace_dir)
    project_candidates = [
        workspace / AGENTS_FILENAME,
        *(workspace / name for name in PROVIDER_SHIM_FILES),
    ]
    use_chezmoi = False
    try:
        use_chezmoi = bool(get_use_chezmoi())
    except Exception:  # noqa: BLE001 - fail-open on config errors.
        use_chezmoi = False
    for candidate in project_candidates:
        if not candidate.is_file():
            continue
        try:
            data = candidate.read_bytes()
        except OSError:
            continue
        oid = git_blob_oid(data)
        repo = _owning_repo(candidate)
        tracked = bool(repo is not None and _is_tracked(repo, candidate))
        if repo is not None and not _blob_exists_in_repo(repo, oid):
            _store_instruction_snapshot_bytes(data, oid)
        entries.append(
            {
                "path": str(candidate),
                "repo": "project" if repo is not None else "none",
                "blob_oid": oid,
                "tracked": tracked,
            }
        )
    for candidate in _home_instruction_candidates():
        if not candidate.is_file():
            continue
        try:
            data = candidate.read_bytes()
        except OSError:
            continue
        oid = git_blob_oid(data)
        if use_chezmoi:
            try:
                chezmoi_root = (
                    CHEZMOI_HOME.parent if CHEZMOI_HOME.name else CHEZMOI_HOME
                )
                if (chezmoi_root / ".git").exists():
                    chezmoi_repo: Path | None = chezmoi_root
                else:
                    chezmoi_repo = _owning_repo(CHEZMOI_HOME)
            except Exception:  # noqa: BLE001 - fail-open.
                chezmoi_repo = None
            if chezmoi_repo is None or not _blob_exists_in_repo(chezmoi_repo, oid):
                _store_instruction_snapshot_bytes(data, oid)
            entries.append(
                {
                    "path": str(candidate),
                    "repo": "chezmoi",
                    "blob_oid": oid,
                    "tracked": False,
                }
            )
        else:
            repo = _owning_repo(candidate)
            if repo is None or not _blob_exists_in_repo(repo, oid):
                _store_instruction_snapshot_bytes(data, oid)
            entries.append(
                {
                    "path": str(candidate),
                    "repo": "none",
                    "blob_oid": oid,
                    "tracked": False,
                }
            )
        break
    return entries


def capture_launch_evidence(
    workspace_dir: str | Path,
    agent_meta: dict[str, Any],
) -> dict[str, Any]:
    """Add workspace HEAD + instruction snapshot to *agent_meta* (fail-open)."""
    try:
        head = capture_workspace_head(workspace_dir)
        if head is not None:
            agent_meta["workspace_head"] = head
    except Exception as exc:  # noqa: BLE001 - capture never blocks launch.
        logger.warning("launch evidence: workspace_head capture failed: %s", exc)
    try:
        agent_meta["instruction_snapshot"] = capture_instruction_snapshot(workspace_dir)
    except Exception as exc:  # noqa: BLE001 - capture never blocks launch.
        logger.warning("launch evidence: instruction_snapshot capture failed: %s", exc)
    return agent_meta


__all__ = [
    "capture_instruction_snapshot",
    "capture_launch_evidence",
    "capture_workspace_head",
]
