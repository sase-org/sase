"""Initialization transaction for split plans/research sidecar repositories."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import TYPE_CHECKING, cast

from sase.sdd._bead_ignore import ensure_bead_store_gitignore
from sase.sdd._commit import (
    commit_sdd_files,
    network_git_timeout,
    run_sdd_git,
)
from sase.sdd._init_files import ensure_sdd_sidecar_initialized
from sase.sdd._paths import get_primary_workspace_dir
from sase.sdd._store_adoption import materialization_lock
from sase.sdd._store_link import ensure_sidecar_sdd_clone
from sase.sdd._store_records import (
    is_materialized_record,
    normalize_sdd_store_record,
    read_sdd_store_record,
    write_sdd_store_record,
)
from sase.sdd._store_types import (
    SDD_STORAGE_SIDECAR_REPOS,
    SDD_STORAGE_SEPARATE_REPO,
    SddSidecar,
    SddMaterializationError,
    SddStore,
    SddStoreRecord,
)

if TYPE_CHECKING:
    from sase.workspace_provider import SddSidecarPreflight

SPLIT_SIDECAR_KINDS = ("plans", "research")


@dataclass(frozen=True)
class _SddSidecarInitOutcome:
    """Completed split-sidecar initialization transaction."""

    store: SddStore
    record: SddStoreRecord
    created: frozenset[str]


def preflight_split_sdd_sidecars(
    workspace_dir: str | Path, workspace_num: int
) -> dict[str, SddSidecarPreflight]:
    """Discover both split sidecars without mutating local or remote state."""

    from sase.workspace_provider import (
        SddSidecarPreflight,
        preflight_sdd_sidecar,
    )

    workspace = Path(workspace_dir).expanduser()
    primary = Path(
        get_primary_workspace_dir(str(workspace), workspace_num)
    ).expanduser()
    results: dict[str, SddSidecarPreflight] = {}
    for kind in SPLIT_SIDECAR_KINDS:
        try:
            result = preflight_sdd_sidecar(
                str(primary),
                str(workspace),
                _provider_options(workspace_num, kind),
            )
        except Exception as exc:  # noqa: BLE001 - provider errors are user-facing.
            raise SddMaterializationError(str(exc) or type(exc).__name__) from exc
        if not isinstance(result, SddSidecarPreflight):
            raise SddMaterializationError(
                "The workspace provider does not support split SDD sidecar "
                "preflight. Update the provider plugin and rerun `sase sdd init`."
            )
        results[kind] = result
    return results


def initialize_split_sdd_sidecars(
    workspace_dir: str | Path,
    workspace_num: int,
    *,
    creation_authorized: dict[str, bool] | None = None,
) -> _SddSidecarInitOutcome:
    """Create/adopt, initialize, push, then record both split sidecars."""

    workspace = Path(workspace_dir).expanduser()
    primary = Path(
        get_primary_workspace_dir(str(workspace), workspace_num)
    ).expanduser()
    authorizations = creation_authorized or {}

    with materialization_lock(primary):
        existing = read_sdd_store_record(primary)
        sidecars: dict[str, SddSidecar] = {}
        provider: str | None = None
        host: str | None = None
        created: set[str] = set()

        for kind in SPLIT_SIDECAR_KINDS:
            existing_sidecar = (
                existing.sidecar_for_kind(kind)
                if is_materialized_record(existing)
                and existing is not None
                and existing.is_sidecar_storage
                else None
            )
            result = _create_or_adopt_sidecar(
                primary,
                workspace,
                workspace_num,
                kind,
                existing_sidecar=existing_sidecar,
                creation_authorized=authorizations.get(kind, False),
            )
            sidecars[kind] = SddSidecar(
                repo=cast(str, result.repo),
                remote_url=cast(str, result.remote_url),
            )
            provider = provider or result.provider
            host = host or result.host
            if result.created:
                created.add(kind)

        from sase.linked_repos import sidecar_repo_clone_dir

        plans_root = Path(sidecar_repo_clone_dir(workspace, "plans"))
        research_root = Path(sidecar_repo_clone_dir(workspace, "research"))
        for kind, root in (("plans", plans_root), ("research", research_root)):
            ensure_sidecar_sdd_clone(root, sidecars[kind].remote_url, strict=True)
            generated = list(ensure_sdd_sidecar_initialized(kind, root))
            if kind == "plans":
                gitignore = ensure_bead_store_gitignore(root)
                if gitignore is not None:
                    generated.append(gitignore)
            committed = bool(generated) and commit_sdd_files(
                root,
                f"Initialize SASE {kind} sidecar",
                auto_commit_type="init",
                paths=generated,
                repo_name=sidecars[kind].repo,
                record_commit_marker=False,
            )
            if committed:
                _push_sidecar(root)

        record = write_sdd_store_record(
            primary,
            SddStoreRecord(
                schema_version=2,
                storage=SDD_STORAGE_SIDECAR_REPOS,
                provider=provider,
                host=host,
                discovery="found",
                plans=sidecars["plans"],
                research=sidecars["research"],
            ),
        )
        return _SddSidecarInitOutcome(
            store=SddStore(
                storage=SDD_STORAGE_SIDECAR_REPOS,
                sdd_dir=plans_root,
                repo_root=plans_root,
                provider=provider,
                remote_url=sidecars["plans"].remote_url,
                research_dir=research_root,
                research_remote_url=sidecars["research"].remote_url,
            ),
            record=record,
            created=frozenset(created),
        )


@dataclass(frozen=True)
class _ProviderSidecar:
    repo: str
    remote_url: str
    provider: str | None
    host: str | None
    created: bool


def _create_or_adopt_sidecar(
    primary: Path,
    workspace: Path,
    workspace_num: int,
    kind: str,
    *,
    existing_sidecar: SddSidecar | None,
    creation_authorized: bool,
) -> _ProviderSidecar:
    from sase.workspace_provider import create_sdd_remote

    options = _provider_options(workspace_num, kind)
    options.update(
        {
            "create": True,
            "sdd_creation_authorized": creation_authorized,
        }
    )
    if existing_sidecar is not None:
        options["sdd_repo"] = existing_sidecar.repo
        options["sdd_remote_url"] = existing_sidecar.remote_url
    try:
        raw = create_sdd_remote(str(primary), str(workspace), options)
        normalized = normalize_sdd_store_record(cast(dict[str, object], raw))
    except Exception as exc:  # noqa: BLE001 - provider errors are user-facing.
        raise SddMaterializationError(str(exc) or type(exc).__name__) from exc
    if normalized.storage != SDD_STORAGE_SEPARATE_REPO:
        raise SddMaterializationError(
            f"provider returned invalid {kind} sidecar storage metadata"
        )
    if not normalized.repo or not normalized.remote_url:
        raise SddMaterializationError(
            f"provider returned incomplete {kind} sidecar metadata"
        )
    created = bool(isinstance(raw, dict) and raw.get("created"))
    return _ProviderSidecar(
        repo=normalized.repo,
        remote_url=normalized.remote_url,
        provider=normalized.provider,
        host=normalized.host,
        created=created,
    )


def _provider_options(workspace_num: int, kind: str) -> dict[str, object]:
    return {
        "create": False,
        "provider_policy": SDD_STORAGE_SEPARATE_REPO,
        "sdd_sidecar_suffix": kind,
        "workspace_num": workspace_num,
    }


def _push_sidecar(root: Path) -> None:
    try:
        run_sdd_git(
            ["push", "origin", "HEAD"],
            cwd=root,
            op="sdd.sidecar_init.push",
            timeout=network_git_timeout(),
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, OSError) as exc:
        raise SddMaterializationError(
            f"failed to push initialized SDD sidecar {root}: {exc}"
        ) from exc
