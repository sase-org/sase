"""Alternates state planning and rollback helpers."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import cast

from sase.core.git_object_sharing import plan_git_object_sharing
from sase.workspace_provider._git_objects_git import (
    alternates_file,
    config_bool,
    config_get_optional,
    git_object_dir,
    set_config,
    unset_config,
)
from sase.workspace_provider._git_objects_model import (
    _BORROWER_CONFIG_KEYS,
    _CONFIG_ENABLED,
    _CONFIG_PRIMARY_OBJECTS,
    AlternateSnapshot,
    AlternateStatus,
    AlternateState,
    GitObjectSharingError,
)


def _read_alternates(path: Path) -> tuple[str, ...]:
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ()
    except OSError as exc:
        raise GitObjectSharingError(f"could not read {path}: {exc}") from exc
    return tuple(line.strip() for line in content.splitlines() if line.strip())


def sharing_plan(
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
            "config_enabled": config_bool(checkout, _CONFIG_ENABLED),
            "config_primary_objects": config_get_optional(
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


def state_from_plan(plan: Mapping[str, object]) -> AlternateState:
    status = cast(AlternateStatus, str(plan["status"]))
    alternates = plan.get("alternates")
    if not isinstance(alternates, list):
        raise GitObjectSharingError("Git object-sharing plan omitted alternates")
    return AlternateState(
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
) -> AlternateState:
    """Inspect and classify a checkout's alternates dependency."""
    return state_from_plan(
        sharing_plan(
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


def apply_alternates_plan(plan: Mapping[str, object]) -> None:
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


def _capture_alternate_snapshot(checkout_dir: str) -> AlternateSnapshot:
    checkout = checkout_dir.rstrip("/")
    path = alternates_file(checkout)
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        content = None
    except OSError as exc:
        raise GitObjectSharingError(f"could not read {path}: {exc}") from exc
    return AlternateSnapshot(
        alternates_file=path,
        alternates_content=content,
        config_values={
            key: config_get_optional(checkout, key) for key in _BORROWER_CONFIG_KEYS
        },
    )


def _restore_alternate_snapshot(
    checkout_dir: str,
    snapshot: AlternateSnapshot,
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
        unset_config(checkout, key)
        value = snapshot.config_values.get(key)
        if value is not None:
            set_config(checkout, key, value)


def with_alternate_rollback[T](
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
