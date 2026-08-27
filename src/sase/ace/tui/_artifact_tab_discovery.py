"""Document-provider discovery behind the Artifacts tab registry.

Walks enabled project records, resolves each workspace's sidecar ref policies,
and reports both the healthy roots and the failures that must stay visible as
degraded tabs.  Callers go through :mod:`sase.ace.tui.artifact_tabs`.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from sase.content_layout import LayoutCollisionError
from sase.config.core import current_config_token
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import effective_project_name
from sase.sidecar_ref_config import sidecar_ref_policy_report, sidecar_role_ref_kind

from ._artifact_tab_model import (
    ProjectProviderRecord,
    ProviderDiscoveryIssue,
    ProviderLoadResult,
)


# Operational failures during provider discovery. Narrower than ``Exception``
# so programming errors (TypeError, NameError, AssertionError) still escape.
_PROVIDER_DISCOVERY_ERRORS: tuple[type[BaseException], ...] = (
    AttributeError,
    ImportError,
    KeyError,
    LayoutCollisionError,
    OSError,
    RuntimeError,
    ValueError,
)


def load_project_provider_records(
    *,
    project: str | None,
) -> ProviderLoadResult:
    """Return document-provider roots and issues for the requested scope."""

    try:
        records = list_project_records(
            sase_projects_dir(),
            "all",
            include_home=False,
            projects_only=True,
        )
    except _PROVIDER_DISCOVERY_ERRORS as exc:
        return ProviderLoadResult(
            records=(),
            issues=(
                ProviderDiscoveryIssue(
                    message=str(exc),
                    code="provider_discovery_failed",
                    kind="plan",
                    source="list_project_records",
                ),
            ),
        )
    project_records = tuple(
        record
        for record in records
        if bool(getattr(record, "is_project", False))
        and not bool(getattr(record, "system_managed", False))
    )
    selected = _select_project_records(project_records, project)
    loaded: list[ProjectProviderRecord] = []
    issues: list[ProviderDiscoveryIssue] = []
    for record in selected:
        workspace_dir = getattr(record, "workspace_dir", None)
        if not workspace_dir:
            continue
        workspace = Path(str(workspace_dir)).expanduser().resolve(strict=False)
        issues.extend(_load_workspace_provider_records(record, workspace, loaded))
    return ProviderLoadResult(
        records=tuple(
            sorted(
                loaded,
                key=lambda item: (
                    item.policy.ref_kind.casefold(),
                    item.display_name.casefold(),
                    item.project,
                    item.role,
                    str(item.root),
                ),
            )
        ),
        issues=tuple(issues),
    )


def _load_workspace_provider_records(
    record: Any,
    workspace: Path,
    loaded: list[ProjectProviderRecord],
) -> tuple[ProviderDiscoveryIssue, ...]:
    from sase._linked_repo_config import resolution_config
    from sase.content_layout import resolve_project_config_read_path
    from sase.sdd.store import document_sidecar_roles, resolve_sdd_store

    issues: list[ProviderDiscoveryIssue] = []
    try:
        store = resolve_sdd_store(workspace, 1)
        roles = document_sidecar_roles(
            store.split_sidecar_roles(),
            include_plans=True,
        )
    except _PROVIDER_DISCOVERY_ERRORS as exc:
        return (
            ProviderDiscoveryIssue(
                message=str(exc),
                code="provider_store_failed",
                kind="plan",
                source=str(workspace),
            ),
        )
    try:
        source_path = resolve_project_config_read_path(workspace)
    except _PROVIDER_DISCOVERY_ERRORS as exc:
        source_path = None
        issues.append(
            ProviderDiscoveryIssue(
                message=str(exc),
                code="provider_config_unavailable",
                kind="plan",
                source=str(workspace),
            )
        )
    try:
        report = sidecar_ref_policy_report(
            resolution_config(str(workspace), None),
            primary_workspace_dir=workspace,
            roles=roles,
            source_path=source_path,
        )
    except _PROVIDER_DISCOVERY_ERRORS as exc:
        issues.append(
            ProviderDiscoveryIssue(
                message=str(exc),
                code="provider_policy_failed",
                kind="plan",
                source=str(source_path or workspace),
            )
        )
        return tuple(issues)

    for diagnostic in report.diagnostics:
        role = diagnostic.role
        if role is None or role in report.policies:
            continue
        issues.append(
            ProviderDiscoveryIssue(
                message=diagnostic.message,
                code=diagnostic.code,
                kind=sidecar_role_ref_kind(role),
                role=role,
                source=None if source_path is None else str(source_path),
            )
        )
    for role in roles:
        policy = report.policies.get(role)
        if policy is None or not policy.is_document:
            continue
        try:
            root = store.kind_root(role)
        except (KeyError, OSError, ValueError):
            continue
        loaded.append(
            ProjectProviderRecord(
                project=str(record.project_name),
                display_name=effective_project_name(record),
                workspace_dir=str(getattr(record, "workspace_dir", workspace)),
                role=role,
                root=root,
                policy=policy,
            )
        )
    return tuple(issues)


def _select_project_records(
    records: tuple[Any, ...], project: str | None
) -> tuple[Any, ...]:
    if project is None:
        return tuple(
            record
            for record in records
            if getattr(record, "state", "enabled") == "enabled"
        )
    folded = project.casefold()
    return tuple(
        record
        for record in records
        if folded
        in {
            str(getattr(record, "project_name", "")).casefold(),
            effective_project_name(record).casefold(),
            *(
                str(alias).casefold()
                for alias in getattr(record, "aliases", ())
                if alias
            ),
        }
    )


# Matches sase.config.core._CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS: computing
# this token walks every configured project's record and stats its config
# file, so callers on the render path (``resolve_artifacts_subtabs`` per
# link-graph chip) must not pay that cost on every lookup.
_PROVIDER_SOURCE_TOKEN_REFRESH_INTERVAL_SECONDS = 0.75
_provider_source_token_cache_value: tuple[object, ...] | None = None
_provider_source_token_cache_deadline = 0.0
_provider_source_token_cache_lock = threading.Lock()


def reset_provider_source_token_cache() -> None:
    """Force the next :func:`provider_source_token` call to recompute."""

    global _provider_source_token_cache_value, _provider_source_token_cache_deadline
    with _provider_source_token_cache_lock:
        _provider_source_token_cache_value = None
        _provider_source_token_cache_deadline = 0.0


def provider_source_token() -> tuple[object, ...] | None:
    """Return a cache key for configured providers, or ``None`` if listing failed.

    Cached for `_PROVIDER_SOURCE_TOKEN_REFRESH_INTERVAL_SECONDS` seconds. An
    expired cache is recomputed synchronously on the next call rather than
    kicking off a background refresh like ``current_config_token()`` does:
    the cost here is one project-lifecycle scan, not a full config merge.

    A ``None`` token is uncacheable so a transient discovery failure cannot
    pin a degraded four-tab answer the way the old ``("unavailable",)``
    sentinel did.
    """

    global _provider_source_token_cache_value, _provider_source_token_cache_deadline
    with _provider_source_token_cache_lock:
        cached = _provider_source_token_cache_value
        if (
            cached is not None
            and time.monotonic() < _provider_source_token_cache_deadline
        ):
            return cached
        token = _compute_provider_source_token()
        if token is not None:
            _provider_source_token_cache_value = token
            _provider_source_token_cache_deadline = (
                time.monotonic() + _PROVIDER_SOURCE_TOKEN_REFRESH_INTERVAL_SECONDS
            )
        return token


def _compute_provider_source_token() -> tuple[object, ...] | None:
    """Inspect every configured project and return the discovery cache key.

    A ``None`` result (transient discovery failure) MUST NOT be cached; see
    :func:`provider_source_token`.
    """

    try:
        records = list_project_records(
            sase_projects_dir(),
            "all",
            include_home=False,
            projects_only=True,
        )
    except _PROVIDER_DISCOVERY_ERRORS:
        return None
    token: list[object] = []
    for record in records:
        if not bool(getattr(record, "is_project", False)) or bool(
            getattr(record, "system_managed", False)
        ):
            continue
        project_file = Path(str(getattr(record, "project_file", "")))
        try:
            stat = project_file.stat()
            project_file_token: object = (
                str(project_file),
                stat.st_mtime_ns,
                stat.st_size,
            )
        except OSError:
            project_file_token = (str(project_file), None, None)
        workspace_dir = getattr(record, "workspace_dir", None)
        config_token: object = None
        if workspace_dir:
            try:
                from sase.content_layout import resolve_project_config_read_path

                config_path = resolve_project_config_read_path(Path(str(workspace_dir)))
                if config_path is not None:
                    config_stat = Path(config_path).stat()
                    config_token = (
                        str(config_path),
                        config_stat.st_mtime_ns,
                        config_stat.st_size,
                    )
            except _PROVIDER_DISCOVERY_ERRORS:
                config_token = None
        token.append(
            (
                getattr(record, "project_name", ""),
                getattr(record, "state", "enabled"),
                effective_project_name(record),
                tuple(getattr(record, "aliases", ())),
                workspace_dir,
                project_file_token,
                config_token,
            )
        )
    token.append(("config", current_config_token()))
    return tuple(token)
