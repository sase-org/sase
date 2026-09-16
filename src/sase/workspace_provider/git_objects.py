"""Shared Git object-store maintenance for managed workspaces."""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from sase.core.git_object_sharing import (
    MUTATION_CONTEXT_EXISTING_REUSE,
    MUTATION_CONTEXT_MAINTENANCE_COMPACT,
    MUTATION_CONTEXT_MAINTENANCE_DISSOCIATE,
    MUTATION_CONTEXT_MAINTENANCE_REPAIR,
    MUTATION_CONTEXT_NEW_CHECKOUT,
    plan_git_object_sharing,
)
from sase.git_lock_retry import run_with_git_lock_retry
from sase.workspace_provider._utils_git import (
    command_output,
    git_result_adapter,
    non_interactive_git_env,
)

AlternateStatus = Literal[
    "absent", "expected", "stale", "broken", "unexpected", "preserved"
]

_CONFIG_ENABLED = "sase.workspaceGitObjects"
_CONFIG_PRIMARY_OBJECTS = "sase.workspaceGitObjectsPrimary"
_CONFIG_PRIMARY_CHECKOUT = "sase.workspaceGitObjectsPrimaryCheckout"
_CONFIG_SOURCE = "sase.workspaceGitObjectsSource"
_BORROWER_CONFIG_KEYS = (
    _CONFIG_ENABLED,
    _CONFIG_PRIMARY_OBJECTS,
    _CONFIG_PRIMARY_CHECKOUT,
    "gc.auto",
    "maintenance.auto",
)


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


@dataclass(frozen=True)
class _AlternateSnapshot:
    """Borrower-local alternates/config state for rollback."""

    alternates_file: Path
    alternates_content: str | None
    config_values: Mapping[str, str | None]


def _run_git(
    cwd: str,
    args: list[str],
    *,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
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
    except OSError as exc:
        raise GitObjectSharingError(
            f"could not run git {' '.join(args)} in {cwd}: {exc}"
        ) from exc
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
    value = _config_get_optional(checkout_dir, key)
    return value or ""


def _config_get_optional(checkout_dir: str, key: str) -> str | None:
    result = _run_git(checkout_dir, ["config", "--local", "--get", key])
    if result.returncode != 0:
        return None
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
    for key in _BORROWER_CONFIG_KEYS:
        _unset_config(checkout_dir, key)


def _read_alternates(path: Path) -> tuple[str, ...]:
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ()
    except OSError as exc:
        raise GitObjectSharingError(f"could not read {path}: {exc}") from exc
    return tuple(line.strip() for line in content.splitlines() if line.strip())


def _sharing_plan(
    primary_checkout_dir: str,
    checkout_dir: str,
    *,
    operation: str,
    mutation_context: str | None = None,
    checkout_clean: bool | None = None,
    fresh_claim_status: str | None = None,
    fresh_occupant_status: str | None = None,
) -> dict[str, object]:
    primary = primary_checkout_dir.rstrip("/")
    checkout = checkout_dir.rstrip("/")
    primary_objects = git_object_dir(primary)
    objects = git_object_dir(checkout)
    alt_file = objects / "info" / "alternates"
    try:
        request: dict[str, object] = {
            "operation": operation,
            "checkout_dir": checkout,
            "object_dir": str(objects),
            "alternates_file": str(alt_file),
            "primary_checkout_dir": primary,
            "primary_object_dir": str(primary_objects),
            "alternates": list(_read_alternates(alt_file)),
            "config_enabled": _config_bool(checkout, _CONFIG_ENABLED),
            "config_primary_objects": _config_get_optional(
                checkout,
                _CONFIG_PRIMARY_OBJECTS,
            ),
        }
        if mutation_context is not None:
            request["mutation_context"] = mutation_context
        if checkout_clean is not None:
            request["checkout_clean"] = checkout_clean
        if fresh_claim_status is not None:
            request["fresh_claim_status"] = fresh_claim_status
        if fresh_occupant_status is not None:
            request["fresh_occupant_status"] = fresh_occupant_status
        return plan_git_object_sharing(request)
    except Exception as exc:
        raise GitObjectSharingError(
            f"could not plan Git object sharing for {checkout}: {exc}"
        ) from exc


def _state_from_plan(plan: Mapping[str, object]) -> _AlternateState:
    status = cast(AlternateStatus, str(plan["status"]))
    alternates = plan.get("alternates")
    if not isinstance(alternates, list):
        raise GitObjectSharingError("Git object-sharing plan omitted alternates")
    return _AlternateState(
        status=status,
        checkout_dir=str(plan["checkout_dir"]),
        object_dir=str(plan["object_dir"]),
        alternates_file=str(plan["alternates_file"]),
        expected_object_dir=str(plan["expected_object_dir"]),
        alternates=tuple(str(value) for value in alternates),
        sase_owned=bool(plan["sase_owned"]),
        detail=str(plan.get("detail") or ""),
    )


def classify_alternate_state(
    checkout_dir: str,
    *,
    primary_checkout_dir: str,
) -> _AlternateState:
    """Inspect and classify a checkout's alternates dependency."""
    return _state_from_plan(
        _sharing_plan(
            primary_checkout_dir,
            checkout_dir,
            operation="classify",
        )
    )


def _write_alternates_content(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=".alternates.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
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


def _write_alternates_file(path: Path, lines: list[str]) -> None:
    if not lines:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise GitObjectSharingError(f"could not remove {path}: {exc}") from exc
        return
    _write_alternates_content(path, "".join(f"{line}\n" for line in lines))


def _apply_alternates_plan(plan: Mapping[str, object]) -> None:
    action = str(plan["action"])
    if action == "fail":
        raise GitObjectSharingError(
            str(plan.get("detail") or "Git object-sharing operation refused")
        )
    if action == "none":
        return
    raw_lines = plan.get("write_alternates")
    if not isinstance(raw_lines, list):
        raise GitObjectSharingError("Git object-sharing plan omitted write_alternates")
    _write_alternates_file(
        Path(str(plan["alternates_file"])),
        [str(line) for line in raw_lines],
    )


def _capture_alternate_snapshot(checkout_dir: str) -> _AlternateSnapshot:
    checkout = checkout_dir.rstrip("/")
    path = _alternates_file(checkout)
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        content = None
    except OSError as exc:
        raise GitObjectSharingError(f"could not read {path}: {exc}") from exc
    return _AlternateSnapshot(
        alternates_file=path,
        alternates_content=content,
        config_values={
            key: _config_get_optional(checkout, key) for key in _BORROWER_CONFIG_KEYS
        },
    )


def _restore_alternate_snapshot(
    checkout_dir: str,
    snapshot: _AlternateSnapshot,
) -> None:
    checkout = checkout_dir.rstrip("/")
    if snapshot.alternates_content is None:
        try:
            snapshot.alternates_file.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise GitObjectSharingError(
                f"could not restore missing {snapshot.alternates_file}: {exc}"
            ) from exc
    else:
        _write_alternates_content(snapshot.alternates_file, snapshot.alternates_content)
    for key in _BORROWER_CONFIG_KEYS:
        _unset_config(checkout, key)
        value = snapshot.config_values.get(key)
        if value is not None:
            _set_config(checkout, key, value)


def _with_alternate_rollback[T](
    checkout_dir: str,
    action: Callable[[], T],
) -> T:
    snapshot = _capture_alternate_snapshot(checkout_dir)
    try:
        return action()
    except Exception as exc:
        try:
            _restore_alternate_snapshot(checkout_dir, snapshot)
        except GitObjectSharingError as rollback:
            raise GitObjectSharingError(
                f"{exc}; rollback also failed: {rollback}"
            ) from exc
        raise


def _apply_install_sase_alternate(
    primary_checkout_dir: str,
    checkout_dir: str,
    *,
    mutation_context: str,
    checkout_clean: bool | None = None,
    fresh_claim_status: str | None = None,
    fresh_occupant_status: str | None = None,
) -> _AlternateState:
    """Install, repoint, or deliberately preserve one borrower's alternate."""

    primary = primary_checkout_dir.rstrip("/")
    checkout = checkout_dir.rstrip("/")
    plan = _sharing_plan(
        primary,
        checkout,
        operation="install",
        mutation_context=mutation_context,
        checkout_clean=checkout_clean,
        fresh_claim_status=fresh_claim_status,
        fresh_occupant_status=fresh_occupant_status,
    )
    if str(plan["action"]) == "fail":
        _apply_alternates_plan(plan)
    planned = _state_from_plan(plan)
    primary_objects = Path(str(plan["expected_object_dir"]))
    dependency_mutation = bool(plan.get("dependency_mutation"))
    # Only record borrower metadata for a dependency that is, or is about to
    # become, the configured primary. When the core preserves a dependency it
    # chose not to repoint, writing our primary into the borrower's config
    # would leave the two disagreeing, and a later classification would read
    # the preserved alternate as foreign.
    configure_metadata = dependency_mutation or planned.status == "expected"

    if not dependency_mutation:
        # The core left the dependency exactly as it found it, so there is no
        # rewrite to verify. Proving connectivity here would fail the caller
        # over a pre-existing condition this call deliberately did not touch --
        # ordinary reuse defers a broken dependency to maintenance repair
        # rather than repointing it underneath a running agent.
        if configure_metadata:
            configure_primary_for_sharing(primary)
            _configure_borrower_for_sharing(
                checkout,
                primary_checkout_dir=primary,
                primary_object_dir=primary_objects,
            )
        return planned

    fsck_connectivity(primary)
    configure_primary_for_sharing(primary)
    _apply_alternates_plan(plan)
    _configure_borrower_for_sharing(
        checkout,
        primary_checkout_dir=primary,
        primary_object_dir=primary_objects,
    )
    fsck_connectivity(checkout)
    return classify_alternate_state(checkout, primary_checkout_dir=primary)


def _install_sase_alternate(
    primary_checkout_dir: str,
    checkout_dir: str,
) -> _AlternateState:
    return _with_alternate_rollback(
        checkout_dir,
        lambda: _apply_install_sase_alternate(
            primary_checkout_dir,
            checkout_dir,
            mutation_context=MUTATION_CONTEXT_NEW_CHECKOUT,
        ),
    )


def ensure_sase_alternate(primary_checkout_dir: str, checkout_dir: str) -> None:
    """Ensure one freshly materialized checkout borrows the primary objects."""

    state = _install_sase_alternate(primary_checkout_dir, checkout_dir)
    if state.status != "expected":
        raise GitObjectSharingError(
            f"alternate for {checkout_dir} is {state.status}, expected shared"
        )


def ensure_sase_alternate_for_reuse(
    primary_checkout_dir: str,
    checkout_dir: str,
) -> None:
    """Validate object sharing while reusing an existing checkout.

    ``sase_core`` never rewrites an existing checkout's object dependency for
    ordinary reuse: a usable one is preserved as it stands and a broken one is
    refused so explicit maintenance can repair it deliberately. A preserved
    dependency is therefore a success -- the checkout keeps working, it just
    does not get repointed underneath an agent that is about to use it.
    """

    checkout = checkout_dir.rstrip("/")
    status = status_porcelain(checkout)
    if status.returncode != 0:
        detail = command_output(status) or "status failed"
        raise GitObjectSharingError(
            "could not prove reusable checkout status before Git object-sharing "
            f"validation: {detail}"
        )
    clean = not status.stdout.strip()
    plan = _sharing_plan(
        primary_checkout_dir,
        checkout,
        operation="install",
        mutation_context=MUTATION_CONTEXT_EXISTING_REUSE,
        checkout_clean=clean,
    )
    if str(plan["action"]) == "fail":
        _apply_alternates_plan(plan)
    if str(plan["action"]) != "none":
        raise GitObjectSharingError(
            "ordinary checkout reuse attempted to mutate Git object-sharing "
            "state; leaving checkout unchanged"
        )


def _remove_sase_alternate(
    primary_checkout_dir: str,
    checkout_dir: str,
    *,
    mutation_context: str,
    fresh_claim_status: str,
    fresh_occupant_status: str,
) -> None:
    """Remove the SASE-owned alternate marker from one borrower."""
    plan = _sharing_plan(
        primary_checkout_dir,
        checkout_dir,
        operation="remove",
        mutation_context=mutation_context,
        fresh_claim_status=fresh_claim_status,
        fresh_occupant_status=fresh_occupant_status,
    )
    _apply_alternates_plan(plan)
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
    *,
    fresh_claim_status: str,
    fresh_occupant_status: str,
) -> _ObjectSharingResult:
    """Install sharing, repack local-only objects, and verify connectivity.

    The caller passes what it freshly observed about the workspace's claim and
    occupant; ``sase_core`` refuses to compact unless both are clear.
    """

    primary = primary_checkout_dir.rstrip("/")
    checkout = checkout_dir.rstrip("/")
    before = checkout_object_bytes(checkout)
    fsck_connectivity(primary)
    status = status_porcelain(checkout)
    clean = status.returncode == 0 and not status.stdout.strip()

    def _compact() -> None:
        _apply_install_sase_alternate(
            primary,
            checkout,
            mutation_context=MUTATION_CONTEXT_MAINTENANCE_COMPACT,
            checkout_clean=clean,
            fresh_claim_status=fresh_claim_status,
            fresh_occupant_status=fresh_occupant_status,
        )
        _run_git(checkout, ["repack", "-a", "-d", "-l"], check=True)
        _run_git(checkout, ["prune-packed"], check=False)
        fsck_connectivity(checkout)

    _with_alternate_rollback(checkout, _compact)
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
    *,
    fresh_claim_status: str,
    fresh_occupant_status: str,
) -> _ObjectSharingResult:
    """Repoint a SASE-owned borrower to the current primary and verify it.

    This is the deliberate maintenance repair that ordinary reuse defers to,
    so ``sase_core`` requires freshly observed clear claim and occupant
    readings before it will rewrite the dependency.
    """

    primary = primary_checkout_dir.rstrip("/")
    checkout = checkout_dir.rstrip("/")
    before = checkout_object_bytes(checkout)
    fsck_connectivity(primary)

    def _repair() -> None:
        _apply_install_sase_alternate(
            primary,
            checkout,
            mutation_context=MUTATION_CONTEXT_MAINTENANCE_REPAIR,
            fresh_claim_status=fresh_claim_status,
            fresh_occupant_status=fresh_occupant_status,
        )
        fsck_connectivity(checkout)

    _with_alternate_rollback(checkout, _repair)
    after = checkout_object_bytes(checkout)
    return _ObjectSharingResult(
        checkout_dir=checkout,
        before_bytes=before,
        after_bytes=after,
        status="repaired",
    )


def dissociate_checkout(
    primary_checkout_dir: str,
    checkout_dir: str,
    *,
    fresh_claim_status: str,
    fresh_occupant_status: str,
) -> _ObjectSharingResult:
    """Copy SASE-borrowed objects locally, remove that alternate, and verify.

    Both the repoint and the removal are maintenance mutations, so each is
    planned with the caller's freshly observed claim and occupant readings.
    """

    primary = primary_checkout_dir.rstrip("/")
    checkout = checkout_dir.rstrip("/")
    before = checkout_object_bytes(checkout)

    def _dissociate() -> None:
        _apply_install_sase_alternate(
            primary,
            checkout,
            mutation_context=MUTATION_CONTEXT_MAINTENANCE_DISSOCIATE,
            fresh_claim_status=fresh_claim_status,
            fresh_occupant_status=fresh_occupant_status,
        )
        fsck_connectivity(checkout)
        _run_git(checkout, ["repack", "-a", "-d"], check=True)
        _remove_sase_alternate(
            primary,
            checkout,
            mutation_context=MUTATION_CONTEXT_MAINTENANCE_DISSOCIATE,
            fresh_claim_status=fresh_claim_status,
            fresh_occupant_status=fresh_occupant_status,
        )
        fsck_connectivity(checkout)

    _with_alternate_rollback(checkout, _dissociate)
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
    "ensure_sase_alternate_for_reuse",
    "fsck_connectivity",
    "git_object_dir",
    "is_git_checkout",
    "repair_shared_checkout",
    "status_porcelain",
]
