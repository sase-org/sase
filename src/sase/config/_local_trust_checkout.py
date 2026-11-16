"""Checkout and selected-config resolution for local-command trust."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from sase.config.core import load_merged_config_for_local_path
from sase.config.local_trust import project_local_commands
from sase.content_layout import (
    LayoutCollisionError,
    discover_project_root,
    owning_checkout_root_for_config,
    resolve_project_config_read_path,
    resolve_project_config_write_path,
)

from ._local_trust_membership import project_identity_for_config
from ._local_trust_support import (
    LocalCommandTrustContext,
    LocalCommandTrustManagementError,
    canonical_path,
)


def _mapping_or_empty(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _logical_config_location(root: Path, selected: Path) -> str:
    """Return the stable project-relative config choice included in the digest."""
    canonical_root = canonical_path(root)
    canonical_selected = canonical_path(selected)
    try:
        relative = canonical_selected.relative_to(canonical_root)
    except ValueError as error:
        raise LocalCommandTrustManagementError(
            f"selected config path {selected} is outside checkout {root}"
        ) from error
    return relative.as_posix()


def _owning_checkout_for_request(
    requested: Path, *, is_config_argument: bool
) -> Path | None:
    """Resolve the checkout root that owns *requested*."""
    if is_config_argument:
        try:
            owned = owning_checkout_root_for_config(requested)
        except LayoutCollisionError:
            raise
        except Exception:
            owned = None
        if owned is not None:
            return owned
    discovered = discover_project_root(requested)
    if discovered is None:
        return None
    try:
        selected = resolve_project_config_read_path(discovered)
    except LayoutCollisionError:
        raise
    except Exception:
        selected = None
    if selected is not None:
        try:
            owned = owning_checkout_root_for_config(selected)
        except LayoutCollisionError:
            raise
        except Exception:
            owned = None
        if owned is not None:
            return owned
    return discovered


def _requested_checkout(path: str | os.PathLike[str] | None) -> tuple[Path, Path]:
    requested = Path.cwd() if path is None else Path(path).expanduser()
    requested = canonical_path(requested)
    is_config_argument = requested.name in {"sase.yml", "sase.yaml"}
    if not requested.exists() and not is_config_argument:
        raise LocalCommandTrustManagementError(f"PATH does not exist: {requested}")
    if requested.is_file() and not is_config_argument:
        raise LocalCommandTrustManagementError(
            "PATH must select a checkout or its selected sase.yml file"
        )
    try:
        root = _owning_checkout_for_request(
            requested, is_config_argument=is_config_argument
        )
    except LayoutCollisionError as exc:
        raise LocalCommandTrustManagementError(str(exc)) from exc
    if root is None:
        raise LocalCommandTrustManagementError(
            f"{requested} is not inside a SASE project checkout"
        )
    root = canonical_path(root)

    try:
        selected = resolve_project_config_read_path(root)
    except LayoutCollisionError as exc:
        raise LocalCommandTrustManagementError(str(exc)) from exc
    if selected is None:
        selected = resolve_project_config_write_path(root)
    selected = Path(os.path.abspath(selected))

    if is_config_argument and canonical_path(requested) != canonical_path(selected):
        raise LocalCommandTrustManagementError(
            f"{requested} is not the selected project config; expected {selected}"
        )
    return root, selected


def _read_local_layer(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as error:
        raise LocalCommandTrustManagementError(
            f"cannot read project config {path}: {error}"
        ) from error
    try:
        value = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise LocalCommandTrustManagementError(
            f"cannot parse project config {path}: {error}"
        ) from error
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise LocalCommandTrustManagementError(
            f"project config {path} must contain a YAML mapping"
        )
    return value


def acknowledgment_target_path(root: Path, identity: str) -> Path:
    """Return the checkout ``sase config trust allow`` should record.

    Project-scoped identities name the primary checkout so numbered
    workspaces inherit that acknowledgment. Checkout-scoped identities
    name *root*.
    """
    prefix = "project:v1:"
    if identity.startswith(prefix):
        primary = identity.rsplit(":", 1)[-1]
        if primary.startswith("/") or (len(primary) >= 2 and primary[1] == ":"):
            return Path(primary)
    return root


def resolve_local_command_trust_context(
    path: str | os.PathLike[str] | None = None,
) -> LocalCommandTrustContext:
    """Read one selected config snapshot and project its executable content."""
    root, config_path = _requested_checkout(path)
    local_layer = _read_local_layer(config_path)
    lower_config = load_merged_config_for_local_path(None)
    logical_location = _logical_config_location(root, config_path)
    projection = project_local_commands(
        local_layer,
        lower_macros=_mapping_or_empty(lower_config.get("macros")),
        lower_workflows=_mapping_or_empty(lower_config.get("workflows")),
        source="local_config",
        config_path=logical_location,
    )
    identity = project_identity_for_config(root, config_path)
    return LocalCommandTrustContext(
        checkout_root=root,
        selected_config_path=config_path,
        logical_config_path=logical_location,
        project_identity=identity,
        projection=projection,
    )


def logical_config_location_for_trust(root: Path, selected: Path) -> str:
    """Return the stable project-relative config choice included in digests.

    Public accessor so enforcement digests the same logical location the
    acknowledgment preview binds.
    """
    return _logical_config_location(root, selected)
