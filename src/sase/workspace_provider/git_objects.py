"""Shared Git object-store maintenance for managed workspaces."""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sase.git_lock_retry import run_with_git_lock_retry
from sase.workspace_provider._utils_git import (
    command_output,
    git_result_adapter,
    non_interactive_git_env,
)

AlternateStatus = Literal["absent", "expected", "stale", "broken", "unexpected"]

_CONFIG_ENABLED = "sase.workspaceGitObjects"
_CONFIG_PRIMARY_OBJECTS = "sase.workspaceGitObjectsPrimary"
_CONFIG_PRIMARY_CHECKOUT = "sase.workspaceGitObjectsPrimaryCheckout"
_CONFIG_SOURCE = "sase.workspaceGitObjectsSource"


class GitObjectSharingError(RuntimeError):
    """Raised when Git object sharing cannot be proven safe."""


@dataclass(frozen=True)
class _AlternateState:
    """Classified ``objects/info/alternates`` state for one checkout."""

    status: AlternateStatus
    checkout_dir: str
    object_dir: str
    alternates_file: str
    expected_object_dir: str
    alternates: tuple[str, ...] = ()
    sase_owned: bool = False
    detail: str = ""


@dataclass(frozen=True)
class _ObjectSharingResult:
    """Result of a compact or repair operation."""

    checkout_dir: str
    before_bytes: int
    after_bytes: int
    status: str
    detail: str = ""

    @property
    def reclaimed_bytes(self) -> int:
        return max(0, self.before_bytes - self.after_bytes)


def _run_git(
    cwd: str,
    args: list[str],
    *,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    result, _outcome = run_with_git_lock_retry(
        lambda: subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            env=non_interactive_git_env(),
            stdin=subprocess.DEVNULL,
        ),
        cwd=cwd,
        result_adapter=git_result_adapter,
    )
    if check and result.returncode != 0:
        detail = command_output(result) or "unknown error"
        raise GitObjectSharingError(f"git {' '.join(args)} failed in {cwd}: {detail}")
    return result


def _git_output(cwd: str, args: list[str]) -> str:
    result = _run_git(cwd, args, check=True)
    return result.stdout.strip()


def _canonical_existing_or_future_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def git_object_dir(checkout_dir: str) -> Path:
    """Return the resolved Git object directory for *checkout_dir*."""

    raw = _git_output(checkout_dir, ["rev-parse", "--git-path", "objects"])
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path(checkout_dir) / path
    return _canonical_existing_or_future_path(path)


def _alternates_file(checkout_dir: str) -> Path:
    return git_object_dir(checkout_dir) / "info" / "alternates"


def _config_get(checkout_dir: str, key: str) -> str:
    result = _run_git(checkout_dir, ["config", "--local", "--get", key])
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _config_bool(checkout_dir: str, key: str) -> bool:
    value = _config_get(checkout_dir, key).strip().lower()
    return value in {"1", "true", "yes", "on"}


def _set_config(checkout_dir: str, key: str, value: str) -> None:
    _run_git(checkout_dir, ["config", "--local", key, value], check=True)


def _unset_config(checkout_dir: str, key: str) -> None:
    result = _run_git(checkout_dir, ["config", "--local", "--unset-all", key])
    if result.returncode not in {0, 5}:
        detail = command_output(result) or "unknown error"
        raise GitObjectSharingError(
            f"could not unset {key} in {checkout_dir}: {detail}"
        )


def configure_primary_for_sharing(primary_checkout_dir: str) -> None:
    """Protect a primary checkout whose objects are borrowed by workspaces."""

    _set_config(primary_checkout_dir, "gc.pruneExpire", "never")
    _set_config(primary_checkout_dir, _CONFIG_SOURCE, "true")


def _configure_borrower_for_sharing(
    checkout_dir: str,
    *,
    primary_checkout_dir: str,
    primary_object_dir: Path,
) -> None:
    """Mark a managed checkout as a SASE-owned Git object borrower."""

    _set_config(checkout_dir, _CONFIG_ENABLED, "true")
    _set_config(checkout_dir, _CONFIG_PRIMARY_OBJECTS, str(primary_object_dir))
    _set_config(
        checkout_dir,
        _CONFIG_PRIMARY_CHECKOUT,
        str(Path(primary_checkout_dir).expanduser().resolve(strict=False)),
    )
    _set_config(checkout_dir, "gc.auto", "0")
    _set_config(checkout_dir, "maintenance.auto", "false")


def _clear_borrower_config(checkout_dir: str) -> None:
    for key in (
        _CONFIG_ENABLED,
        _CONFIG_PRIMARY_OBJECTS,
        _CONFIG_PRIMARY_CHECKOUT,
        "gc.auto",
        "maintenance.auto",
    ):
        _unset_config(checkout_dir, key)


def _read_alternates(path: Path) -> tuple[str, ...]:
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ()
    except OSError as exc:
        raise GitObjectSharingError(f"could not read {path}: {exc}") from exc
    return tuple(line.strip() for line in content.splitlines() if line.strip())


def _resolve_alternate(line: str, *, alternates_path: Path) -> Path:
    path = Path(line).expanduser()
    if not path.is_absolute():
        path = alternates_path.parent / path
    return _canonical_existing_or_future_path(path)


def classify_alternate_state(
    checkout_dir: str,
    *,
    primary_checkout_dir: str,
) -> _AlternateState:
    """Inspect and classify a checkout's alternates dependency."""

    checkout = checkout_dir.rstrip("/")
    primary_objects = git_object_dir(primary_checkout_dir.rstrip("/"))
    objects = git_object_dir(checkout)
    alt_file = objects / "info" / "alternates"
    lines = _read_alternates(alt_file)
    stored_primary = _config_get(checkout, _CONFIG_PRIMARY_OBJECTS)
    sase_owned = _config_bool(checkout, _CONFIG_ENABLED) or bool(stored_primary)

    if not lines:
        return _AlternateState(
            status="absent",
            checkout_dir=checkout,
            object_dir=str(objects),
            alternates_file=str(alt_file),
            expected_object_dir=str(primary_objects),
            alternates=(),
            sase_owned=sase_owned,
        )

    resolved = tuple(
        str(_resolve_alternate(line, alternates_path=alt_file)) for line in lines
    )
    if str(primary_objects) in resolved:
        return _AlternateState(
            status="expected",
            checkout_dir=checkout,
            object_dir=str(objects),
            alternates_file=str(alt_file),
            expected_object_dir=str(primary_objects),
            alternates=resolved,
            sase_owned=True,
        )

    broken = [path for path in resolved if not Path(path).is_dir()]
    if sase_owned:
        status: AlternateStatus = "broken" if broken else "stale"
        detail = (
            f"missing alternate object dir: {broken[0]}"
            if broken
            else "alternate points at a different object dir"
        )
        return _AlternateState(
            status=status,
            checkout_dir=checkout,
            object_dir=str(objects),
            alternates_file=str(alt_file),
            expected_object_dir=str(primary_objects),
            alternates=resolved,
            sase_owned=True,
            detail=detail,
        )

    status = "broken" if broken else "unexpected"
    detail = (
        f"missing alternate object dir: {broken[0]}"
        if broken
        else "alternate is not SASE-managed"
    )
    return _AlternateState(
        status=status,
        checkout_dir=checkout,
        object_dir=str(objects),
        alternates_file=str(alt_file),
        expected_object_dir=str(primary_objects),
        alternates=resolved,
        sase_owned=False,
        detail=detail,
    )


def _write_alternates_file(path: Path, object_dir: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=".alternates.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f"{object_dir}\n")
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(temp_path, path)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def _install_sase_alternate(
    primary_checkout_dir: str,
    checkout_dir: str,
) -> _AlternateState:
    """Install or repoint the SASE-owned alternate for one borrower."""

    primary = primary_checkout_dir.rstrip("/")
    checkout = checkout_dir.rstrip("/")
    state = classify_alternate_state(checkout, primary_checkout_dir=primary)
    if state.status == "unexpected" or (
        state.status == "broken" and not state.sase_owned
    ):
        raise GitObjectSharingError(
            f"refusing to overwrite non-SASE alternate for {checkout}: {state.detail}"
        )

    primary_objects = Path(state.expected_object_dir)
    configure_primary_for_sharing(primary)
    _write_alternates_file(Path(state.alternates_file), primary_objects)
    _configure_borrower_for_sharing(
        checkout,
        primary_checkout_dir=primary,
        primary_object_dir=primary_objects,
    )
    return classify_alternate_state(checkout, primary_checkout_dir=primary)


def ensure_sase_alternate(primary_checkout_dir: str, checkout_dir: str) -> None:
    """Ensure one managed checkout borrows the configured primary objects."""

    state = _install_sase_alternate(primary_checkout_dir, checkout_dir)
    if state.status != "expected":
        raise GitObjectSharingError(
            f"alternate for {checkout_dir} is {state.status}, expected shared"
        )


def _remove_sase_alternate(checkout_dir: str) -> None:
    """Remove the SASE-owned alternate marker from one borrower."""

    path = _alternates_file(checkout_dir.rstrip("/"))
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise GitObjectSharingError(f"could not remove {path}: {exc}") from exc
    _clear_borrower_config(checkout_dir.rstrip("/"))


def _object_dir_bytes(object_dir: str | Path) -> int:
    """Measure local object storage without following symlinks."""

    root = Path(object_dir)
    if not root.exists():
        return 0

    total = 0
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        stat = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                    else:
                        total += stat.st_size
        except OSError:
            continue
    return total


def checkout_object_bytes(checkout_dir: str) -> int:
    return _object_dir_bytes(git_object_dir(checkout_dir.rstrip("/")))


def is_git_checkout(checkout_dir: str) -> bool:
    result = _run_git(checkout_dir.rstrip("/"), ["rev-parse", "--is-inside-work-tree"])
    return result.returncode == 0 and result.stdout.strip() == "true"


def status_porcelain(checkout_dir: str) -> subprocess.CompletedProcess[str]:
    return _run_git(checkout_dir.rstrip("/"), ["status", "--porcelain"])


def fsck_connectivity(checkout_dir: str) -> None:
    _run_git(checkout_dir.rstrip("/"), ["fsck", "--connectivity-only"], check=True)


def compact_checkout(
    primary_checkout_dir: str,
    checkout_dir: str,
) -> _ObjectSharingResult:
    """Install sharing, repack local-only objects, and verify connectivity."""

    checkout = checkout_dir.rstrip("/")
    before = checkout_object_bytes(checkout)
    _install_sase_alternate(primary_checkout_dir.rstrip("/"), checkout)
    _run_git(checkout, ["repack", "-a", "-d", "-l"], check=True)
    _run_git(checkout, ["prune-packed"], check=False)
    fsck_connectivity(checkout)
    after = checkout_object_bytes(checkout)
    return _ObjectSharingResult(
        checkout_dir=checkout,
        before_bytes=before,
        after_bytes=after,
        status="compacted",
    )


def repair_shared_checkout(
    primary_checkout_dir: str,
    checkout_dir: str,
) -> _ObjectSharingResult:
    """Repoint a SASE-owned borrower to the current primary and verify it."""

    checkout = checkout_dir.rstrip("/")
    before = checkout_object_bytes(checkout)
    _install_sase_alternate(primary_checkout_dir.rstrip("/"), checkout)
    fsck_connectivity(checkout)
    after = checkout_object_bytes(checkout)
    return _ObjectSharingResult(
        checkout_dir=checkout,
        before_bytes=before,
        after_bytes=after,
        status="repaired",
    )


def dissociate_checkout(checkout_dir: str) -> _ObjectSharingResult:
    """Copy borrowed objects locally, remove the alternate, and verify."""

    checkout = checkout_dir.rstrip("/")
    before = checkout_object_bytes(checkout)
    alt_path = _alternates_file(checkout)
    original = ""
    if alt_path.exists():
        original = alt_path.read_text(encoding="utf-8")
    _run_git(checkout, ["repack", "-a", "-d"], check=True)
    try:
        _remove_sase_alternate(checkout)
        fsck_connectivity(checkout)
    except Exception:
        if original:
            alt_path.parent.mkdir(parents=True, exist_ok=True)
            alt_path.write_text(original, encoding="utf-8")
        raise
    after = checkout_object_bytes(checkout)
    return _ObjectSharingResult(
        checkout_dir=checkout,
        before_bytes=before,
        after_bytes=after,
        status="dissociated",
    )


__all__ = [
    "GitObjectSharingError",
    "checkout_object_bytes",
    "classify_alternate_state",
    "compact_checkout",
    "configure_primary_for_sharing",
    "dissociate_checkout",
    "ensure_sase_alternate",
    "fsck_connectivity",
    "git_object_dir",
    "is_git_checkout",
    "repair_shared_checkout",
    "status_porcelain",
]
