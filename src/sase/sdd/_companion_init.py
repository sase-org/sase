"""Initialization transaction for split plans/research companion repositories."""

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
from sase.sdd._init_files import ensure_sdd_companion_initialized
from sase.sdd._paths import get_primary_workspace_dir
from sase.sdd._store_adoption import materialization_lock
from sase.sdd._store_link import ensure_companion_sdd_clone
from sase.sdd._store_records import (
    is_materialized_record,
    normalize_sdd_store_record,
    read_sdd_store_record,
    write_sdd_store_record,
)
from sase.sdd._store_types import (
    SDD_STORAGE_COMPANION_REPOS,
    SDD_STORAGE_SEPARATE_REPO,
    SddCompanion,
    SddMaterializationError,
    SddStore,
    SddStoreRecord,
)

if TYPE_CHECKING:
    from sase.workspace_provider import SddCompanionPreflight

SPLIT_COMPANION_KINDS = ("plans", "research")


@dataclass(frozen=True)
class _SddCompanionInitOutcome:
    """Completed split-companion initialization transaction."""

    store: SddStore
    record: SddStoreRecord
    created: frozenset[str]


def preflight_split_sdd_companions(
    workspace_dir: str | Path, workspace_num: int
) -> dict[str, SddCompanionPreflight]:
    """Discover both split companions without mutating local or remote state."""

    from sase.workspace_provider import (
        SddCompanionPreflight,
        preflight_sdd_companion,
    )

    workspace = Path(workspace_dir).expanduser()
    primary = Path(
        get_primary_workspace_dir(str(workspace), workspace_num)
    ).expanduser()
    results: dict[str, SddCompanionPreflight] = {}
    for kind in SPLIT_COMPANION_KINDS:
        try:
            result = preflight_sdd_companion(
                str(primary),
                str(workspace),
                _provider_options(workspace_num, kind),
            )
        except Exception as exc:  # noqa: BLE001 - provider errors are user-facing.
            raise SddMaterializationError(str(exc) or type(exc).__name__) from exc
        if not isinstance(result, SddCompanionPreflight):
            raise SddMaterializationError(
                "The workspace provider does not support split SDD companion "
                "preflight. Update the provider plugin and rerun `sase sdd init`."
            )
        results[kind] = result
    return results


def initialize_split_sdd_companions(
    workspace_dir: str | Path,
    workspace_num: int,
    *,
    creation_authorized: dict[str, bool] | None = None,
) -> _SddCompanionInitOutcome:
    """Create/adopt, initialize, push, then record both split companions."""

    workspace = Path(workspace_dir).expanduser()
    primary = Path(
        get_primary_workspace_dir(str(workspace), workspace_num)
    ).expanduser()
    authorizations = creation_authorized or {}

    with materialization_lock(primary):
        existing = read_sdd_store_record(primary)
        companions: dict[str, SddCompanion] = {}
        provider: str | None = None
        host: str | None = None
        created: set[str] = set()

        for kind in SPLIT_COMPANION_KINDS:
            existing_companion = (
                existing.companion_for_kind(kind)
                if is_materialized_record(existing)
                and existing is not None
                and existing.is_companion_storage
                else None
            )
            result = _create_or_adopt_companion(
                primary,
                workspace,
                workspace_num,
                kind,
                existing_companion=existing_companion,
                creation_authorized=authorizations.get(kind, False),
            )
            companions[kind] = SddCompanion(
                repo=cast(str, result.repo),
                remote_url=cast(str, result.remote_url),
            )
            provider = provider or result.provider
            host = host or result.host
            if result.created:
                created.add(kind)

        plans_root = _companion_clone_dir(workspace, companions["plans"].repo)
        research_root = _companion_clone_dir(workspace, companions["research"].repo)
        for kind, root in (("plans", plans_root), ("research", research_root)):
            ensure_companion_sdd_clone(root, companions[kind].remote_url, strict=True)
            generated = list(ensure_sdd_companion_initialized(kind, root))
            if kind == "plans":
                gitignore = ensure_bead_store_gitignore(root)
                if gitignore is not None:
                    generated.append(gitignore)
            committed = bool(generated) and commit_sdd_files(
                root,
                f"Initialize SASE {kind} companion",
                auto_commit_type="init",
                paths=generated,
                repo_name=companions[kind].repo,
                record_commit_marker=False,
            )
            if committed:
                _push_companion(root)

        record = write_sdd_store_record(
            primary,
            SddStoreRecord(
                schema_version=2,
                storage=SDD_STORAGE_COMPANION_REPOS,
                provider=provider,
                host=host,
                discovery="found",
                plans=companions["plans"],
                research=companions["research"],
            ),
        )
        return _SddCompanionInitOutcome(
            store=SddStore(
                storage=SDD_STORAGE_COMPANION_REPOS,
                sdd_dir=plans_root,
                repo_root=plans_root,
                provider=provider,
                remote_url=companions["plans"].remote_url,
                research_dir=research_root,
                research_remote_url=companions["research"].remote_url,
            ),
            record=record,
            created=frozenset(created),
        )


@dataclass(frozen=True)
class _ProviderCompanion:
    repo: str
    remote_url: str
    provider: str | None
    host: str | None
    created: bool


def _create_or_adopt_companion(
    primary: Path,
    workspace: Path,
    workspace_num: int,
    kind: str,
    *,
    existing_companion: SddCompanion | None,
    creation_authorized: bool,
) -> _ProviderCompanion:
    from sase.workspace_provider import create_sdd_remote

    options = _provider_options(workspace_num, kind)
    options.update(
        {
            "create": True,
            "sdd_creation_authorized": creation_authorized,
        }
    )
    if existing_companion is not None:
        options["sdd_repo"] = existing_companion.repo
        options["sdd_remote_url"] = existing_companion.remote_url
    try:
        raw = create_sdd_remote(str(primary), str(workspace), options)
        normalized = normalize_sdd_store_record(cast(dict[str, object], raw))
    except Exception as exc:  # noqa: BLE001 - provider errors are user-facing.
        raise SddMaterializationError(str(exc) or type(exc).__name__) from exc
    if normalized.storage != SDD_STORAGE_SEPARATE_REPO:
        raise SddMaterializationError(
            f"provider returned invalid {kind} companion storage metadata"
        )
    if not normalized.repo or not normalized.remote_url:
        raise SddMaterializationError(
            f"provider returned incomplete {kind} companion metadata"
        )
    created = bool(isinstance(raw, dict) and raw.get("created"))
    return _ProviderCompanion(
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
        "sdd_companion_suffix": kind,
        "workspace_num": workspace_num,
    }


def _companion_clone_dir(workspace: Path, repo: str) -> Path:
    from sase.linked_repos import companion_repo_clone_dir

    name = repo.rstrip("/").rsplit("/", 1)[-1]
    return Path(companion_repo_clone_dir(workspace, name))


def _push_companion(root: Path) -> None:
    try:
        run_sdd_git(
            ["push", "origin", "HEAD"],
            cwd=root,
            op="sdd.companion_init.push",
            timeout=network_git_timeout(),
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, OSError) as exc:
        raise SddMaterializationError(
            f"failed to push initialized SDD companion {root}: {exc}"
        ) from exc
