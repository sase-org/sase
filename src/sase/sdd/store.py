"""Provider-owned SDD storage resolution and materialization."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import subprocess
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from sase.workspace_provider import SddCompanionPreflight

from sase.sdd._paths import get_primary_workspace_dir
from sase.sdd._store_adoption import (
    adopt_provider_store,
    cleanup_staging,
    clone_matches_record,
    legacy_adoption_needed,
    materialization_lock,
    new_staging_path,
)
from sase.sdd._store_link import ensure_workspace_sdd_clone as _ensure_sdd_clone
from sase.sdd._store_records import (
    coerce_sdd_store_record,
    delete_sdd_store_record,
    is_materialized_record,
    load_sdd_store_record,
    normalize_sdd_store_record,
    optional_str,
    read_sdd_store_record,
    record_cache,
    record_to_json,
    sdd_store_record_path,
    store_not_materialized_message,
    write_sdd_store_record,
)
from sase.sdd._store_types import (
    _STORAGE_VALUES,
    SDD_STORAGE_COMPANION_REPOS,
    SDD_STORAGE_IN_TREE,
    SDD_STORAGE_LOCAL,
    SDD_STORAGE_SEPARATE_REPO,
    SDD_STORE_RECORD_FILENAME,
    SddMaterializationError,
    SddCompanion,
    SddPushAfterCommit,
    SddStorage,
    SddStore,
    SddStoreRecord,
)

_logger = logging.getLogger(__name__)

_coerce_sdd_store_record = coerce_sdd_store_record
_is_materialized_record = is_materialized_record
_load_sdd_store_record = load_sdd_store_record
_optional_str = optional_str
_record_cache = record_cache
_record_to_json = record_to_json
_sdd_store_record_path = sdd_store_record_path
_store_not_materialized_message = store_not_materialized_message
_write_sdd_store_record = write_sdd_store_record

__all__ = [
    "SDD_STORAGE_IN_TREE",
    "SDD_STORAGE_LOCAL",
    "SDD_STORAGE_COMPANION_REPOS",
    "SDD_STORAGE_SEPARATE_REPO",
    "SDD_STORE_RECORD_FILENAME",
    "SddInitOutcome",
    "SddCompanion",
    "SddMaterializationError",
    "SddPushAfterCommit",
    "SddStorage",
    "SddStore",
    "SddStoreRecord",
    "_coerce_sdd_store_record",
    "_is_materialized_record",
    "_load_sdd_store_record",
    "_optional_str",
    "_record_cache",
    "_record_to_json",
    "_refresh_materialized_store",
    "_sdd_store_record_path",
    "_store_not_materialized_message",
    "_write_sdd_store_record",
    "create_and_materialize_sdd_store",
    "delete_sdd_store_record",
    "ensure_workspace_sdd_clone",
    "ensure_sdd_kind_clone",
    "materialized_sdd_clone",
    "materialize_sdd_store",
    "preflight_sdd_companion",
    "normalize_sdd_store_record",
    "read_sdd_store_record",
    "resolve_sdd_dir",
    "resolve_sdd_kind_dir",
    "resolve_sdd_store",
    "write_sdd_store_record",
]


@dataclass(frozen=True)
class SddInitOutcome:
    """Result of provider-owned SDD initialization."""

    store: SddStore
    repo: str | None
    remote_url: str | None
    created: bool


def resolve_sdd_dir(workspace_dir: str | Path, workspace_num: int) -> Path:
    """Resolve the effective SDD root without network or filesystem writes."""

    return resolve_sdd_store(workspace_dir, workspace_num).sdd_dir


def resolve_sdd_kind_dir(
    workspace_dir: str | Path, workspace_num: int, kind: str
) -> Path:
    """Resolve one logical SDD kind without materializing its backing clone."""

    return resolve_sdd_store(workspace_dir, workspace_num).kind_root(kind)


def resolve_sdd_store(workspace_dir: str | Path, workspace_num: int) -> SddStore:
    """Resolve provider-owned storage policy and concrete filesystem paths."""

    storage, record, _primary = _resolve_sdd_storage(workspace_dir, workspace_num)
    if storage == SDD_STORAGE_COMPANION_REPOS:
        assert record is not None and record.plans is not None
        assert record.research is not None
        plans_dir = _companion_clone_dir(workspace_dir, record.plans.repo)
        research_dir = _companion_clone_dir(workspace_dir, record.research.repo)
        return SddStore(
            storage=storage,
            sdd_dir=plans_dir,
            repo_root=plans_dir,
            provider=record.provider,
            remote_url=record.plans.remote_url,
            research_dir=research_dir,
            research_remote_url=record.research.remote_url,
        )

    sdd_dir = _sdd_dir_for_storage(workspace_dir, workspace_num, storage)
    provider: str | None = None
    remote_url: str | None = None
    if _is_materialized_record(record) and storage == SDD_STORAGE_SEPARATE_REPO:
        assert record is not None
        provider = record.provider
        remote_url = record.remote_url
    return SddStore(
        storage=storage,
        sdd_dir=sdd_dir,
        repo_root=sdd_dir,
        provider=provider,
        remote_url=remote_url,
    )


def materialized_sdd_clone(
    primary_workspace_dir: str | Path,
) -> Path | None:
    """Return the primary companion clone when its store was materialized."""

    primary = Path(primary_workspace_dir).expanduser()
    record = read_sdd_store_record(primary)
    if not _is_materialized_record(record):
        return None

    assert record is not None
    if record.is_companion_storage:
        if record.plans is None:
            return None
        clone = _companion_clone_dir(primary, record.plans.repo)
        store = resolve_sdd_store(primary, 1)
        from sase.sdd._store_link import is_matching_store_clone

        return (
            clone if clone.is_dir() and is_matching_store_clone(clone, store) else None
        )

    clone = primary / ".sase" / "sdd"
    if not clone.is_dir():
        return None

    return clone if clone_matches_record(clone, record) else None


def materialize_sdd_store(
    workspace_dir: str | Path,
    workspace_num: int,
    *,
    sdd_creation_authorized: bool | None = None,
) -> SddStore:
    """Materialize the provider-selected store or fail without a local fallback.

    ``sdd_creation_authorized`` is an explicit-init guard. Omitting it preserves
    provider-owned behavior for other materialization consumers; passing a
    boolean requires providers to honor that per-invocation authorization.
    """

    store, _created = _materialize_sdd_store(
        workspace_dir,
        workspace_num,
        sdd_creation_authorized=sdd_creation_authorized,
    )
    return store


def preflight_sdd_companion(
    workspace_dir: str | Path,
    workspace_num: int,
) -> SddCompanionPreflight:
    """Return authoritative, read-only provider discovery for explicit init."""
    from sase.workspace_provider import (
        SddCompanionPreflight,
        preflight_sdd_companion as dispatch,
    )

    workspace = Path(workspace_dir).expanduser()
    primary = Path(
        get_primary_workspace_dir(str(workspace), workspace_num)
    ).expanduser()
    record = read_sdd_store_record(primary)

    options = _provider_options(
        workspace,
        workspace_num,
        policy=SDD_STORAGE_SEPARATE_REPO,
        existing_record=(
            cast(SddStoreRecord, record) if _is_materialized_record(record) else None
        ),
    )
    try:
        result = dispatch(str(primary), str(workspace), options)
    except Exception as exc:  # noqa: BLE001 - provider failures are user-facing.
        raise SddMaterializationError(str(exc) or type(exc).__name__) from exc
    if not isinstance(result, SddCompanionPreflight):
        raise SddMaterializationError(
            "The workspace provider does not support authoritative SDD companion "
            "preflight. Update the provider plugin and rerun `sase sdd init`."
        )
    return result


def create_and_materialize_sdd_store(
    workspace_dir: str | Path,
    workspace_num: int,
) -> SddInitOutcome:
    """Compatibility name for the unified provider-owned materialization path."""

    store, created = _materialize_sdd_store(workspace_dir, workspace_num)
    primary = Path(get_primary_workspace_dir(str(Path(workspace_dir)), workspace_num))
    record = read_sdd_store_record(primary)
    return SddInitOutcome(
        store=store,
        repo=record.repo if record else None,
        remote_url=record.remote_url if record else None,
        created=created,
    )


def _materialize_sdd_store(
    workspace_dir: str | Path,
    workspace_num: int,
    *,
    sdd_creation_authorized: bool | None = None,
) -> tuple[SddStore, bool]:
    workspace = Path(workspace_dir).expanduser()
    primary = Path(
        get_primary_workspace_dir(str(workspace), workspace_num)
    ).expanduser()
    record = read_sdd_store_record(primary)

    if _is_companion_record(record):
        ensure_workspace_sdd_clone(workspace, workspace_num, strict=True)
        return resolve_sdd_store(workspace, workspace_num), False

    if _usable_primary_record(primary, record) and not _legacy_adoption_needed(
        primary, workspace, record
    ):
        return _finalize_existing_store(primary, workspace, workspace_num), False

    policy = (
        None
        if _is_materialized_record(record)
        else _provider_sdd_storage_policy(workspace)
    )
    if policy != SDD_STORAGE_SEPARATE_REPO and not _is_materialized_record(record):
        return resolve_sdd_store(workspace, workspace_num), False

    with materialization_lock(primary):
        record = read_sdd_store_record(primary)
        usable_record = _usable_primary_record(primary, record)
        if usable_record and not _legacy_adoption_needed(primary, workspace, record):
            return _finalize_existing_store(primary, workspace, workspace_num), False

        # Only recognized negative records are stale cache entries. Foreign or
        # malformed records fail while loading, before this replacement path.
        # Positive records remain authoritative until a transaction succeeds.
        if (
            not _is_materialized_record(record)
            and sdd_store_record_path(primary).exists()
        ):
            delete_sdd_store_record(primary)

        staging = new_staging_path(primary)
        try:
            if usable_record:
                assert record is not None
                normalized = record
                created = False
            else:
                result = _provider_materialization_result(
                    primary,
                    workspace,
                    workspace_num,
                    policy=policy,
                    existing_record=(
                        cast(SddStoreRecord, record)
                        if _is_materialized_record(record)
                        else None
                    ),
                    staging=staging,
                    sdd_creation_authorized=sdd_creation_authorized,
                )
                normalized = normalize_sdd_store_record(result)
                created = bool(result.get("created"))
            if not _is_materialized_record(normalized):
                raise SddMaterializationError(
                    "The workspace provider did not create or find the required "
                    "companion SDD repository. Update the provider plugin and rerun "
                    "`sase sdd init`."
                )
            if not normalized.remote_url:
                raise SddMaterializationError(
                    "The workspace provider returned no companion clone URL. Update "
                    "the provider plugin and rerun `sase sdd init`."
                )

            adopt_provider_store(primary, workspace, normalized, staging)
            write_sdd_store_record(primary, normalized)
            try:
                ensure_workspace_sdd_clone(workspace, workspace_num, strict=True)
            except Exception:
                delete_sdd_store_record(primary)
                raise

            store = resolve_sdd_store(workspace, workspace_num)
            _refresh_materialized_store(store.sdd_dir)
            _ensure_materialized_store_initialized(store)
            return resolve_sdd_store(workspace, workspace_num), created
        finally:
            cleanup_staging(staging)


def _usable_primary_record(primary: Path, record: SddStoreRecord | None) -> bool:
    return bool(
        _is_materialized_record(record)
        and clone_matches_record(
            primary / ".sase" / "sdd", cast(SddStoreRecord, record)
        )
    )


def _legacy_adoption_needed(
    primary: Path,
    workspace: Path,
    record: SddStoreRecord | None,
) -> bool:
    return bool(
        _is_materialized_record(record)
        and legacy_adoption_needed(
            primary,
            workspace,
            cast(SddStoreRecord, record),
        )
    )


def _finalize_existing_store(
    primary: Path,
    workspace: Path,
    workspace_num: int,
) -> SddStore:
    ensure_workspace_sdd_clone(workspace, workspace_num, strict=True)
    store = resolve_sdd_store(workspace, workspace_num)
    _refresh_materialized_store(store.sdd_dir)
    _ensure_materialized_store_initialized(store)
    return resolve_sdd_store(workspace, workspace_num)


def ensure_workspace_sdd_clone(
    workspace_dir: str | Path,
    workspace_num: int,
    *,
    strict: bool = False,
) -> None:
    """Ensure a workspace-local clone, optionally failing the setup transaction."""

    store = resolve_sdd_store(workspace_dir, workspace_num)
    if store.is_companion_storage:
        ensure_sdd_kind_clone(workspace_dir, workspace_num, "plans", strict=strict)
        return

    _ensure_sdd_clone(
        workspace_dir,
        workspace_num,
        resolve_store=resolve_sdd_store,
        primary_workspace_dir=get_primary_workspace_dir,
        strict=strict,
    )


def ensure_sdd_kind_clone(
    workspace_dir: str | Path,
    workspace_num: int,
    kind: str,
    *,
    strict: bool = False,
) -> Path:
    """Materialize and synchronize the companion clone backing *kind*."""

    store = resolve_sdd_store(workspace_dir, workspace_num)
    root = store.kind_root(kind)
    if not store.is_companion_storage:
        if store.storage == SDD_STORAGE_SEPARATE_REPO:
            ensure_workspace_sdd_clone(workspace_dir, workspace_num, strict=strict)
        return root

    remote_url = store.research_remote_url if kind == "research" else store.remote_url
    if remote_url is None:
        if strict:
            raise SddMaterializationError(f"no remote URL recorded for SDD kind {kind}")
        return root

    from sase.sdd._store_link import ensure_companion_sdd_clone

    ensure_companion_sdd_clone(
        root if kind != "beads" else root.parent, remote_url, strict=strict
    )
    return root


def _resolve_sdd_storage(
    workspace_dir: str | Path,
    workspace_num: int,
) -> tuple[SddStorage, SddStoreRecord | None, Path]:
    workspace = Path(workspace_dir).expanduser()
    primary = Path(get_primary_workspace_dir(str(workspace), workspace_num))
    record = read_sdd_store_record(primary)
    if _is_materialized_record(record):
        assert record is not None
        return record.storage, record, primary

    policy = _provider_sdd_storage_policy(workspace)
    storage = policy if policy in _STORAGE_VALUES else SDD_STORAGE_LOCAL
    return cast(SddStorage, storage), record, primary


def _sdd_dir_for_storage(
    workspace_dir: str | Path,
    workspace_num: int,
    storage: SddStorage,
) -> Path:
    workspace = Path(workspace_dir)
    if storage == SDD_STORAGE_IN_TREE:
        return workspace / "sdd"
    if storage == SDD_STORAGE_SEPARATE_REPO:
        return workspace / ".sase" / "sdd"
    primary = get_primary_workspace_dir(str(workspace), workspace_num)
    return Path(primary) / ".sase" / "sdd"


def _companion_clone_dir(workspace_dir: str | Path, repo: str) -> Path:
    from sase.linked_repos import resolve_linked_repo_clone_dir

    name = repo.rstrip("/").rsplit("/", 1)[-1]
    return Path(resolve_linked_repo_clone_dir(workspace_dir, name))


def _is_companion_record(record: SddStoreRecord | None) -> bool:
    return bool(
        _is_materialized_record(record)
        and record is not None
        and record.is_companion_storage
    )


def _provider_sdd_storage_policy(workspace_dir: str | Path) -> SddStorage | None:
    vcs_name = _detect_vcs_name(workspace_dir)
    if not vcs_name:
        return None
    try:
        from sase.workspace_provider import get_sdd_storage_policy_by_vcs

        policy = get_sdd_storage_policy_by_vcs(vcs_name)
    except Exception as exc:
        raise SddMaterializationError(
            f"could not resolve SDD storage policy for workspace provider "
            f"{vcs_name!r}: {str(exc) or type(exc).__name__}"
        ) from exc
    if policy is None or policy == "":
        return None
    if policy not in _STORAGE_VALUES:
        raise SddMaterializationError(
            f"workspace provider {vcs_name!r} declared invalid SDD storage policy "
            f"{policy!r}"
        )
    return cast(SddStorage, policy)


def _detect_vcs_name(workspace_dir: str | Path) -> str | None:
    try:
        from sase.vcs_provider import detect_vcs

        return detect_vcs(str(Path(workspace_dir).expanduser()))
    except Exception:
        return None


def _provider_materialization_result(
    primary: Path,
    workspace: Path,
    workspace_num: int,
    *,
    policy: SddStorage | None,
    existing_record: SddStoreRecord | None,
    staging: Path,
    sdd_creation_authorized: bool | None,
) -> dict[str, Any]:
    options = _provider_options(
        workspace,
        workspace_num,
        policy=policy,
        existing_record=existing_record,
    )
    options.update(
        {
            "workspace_num": workspace_num,
            "staging_dir": str(staging),
            "create": True,
        }
    )
    if sdd_creation_authorized is not None:
        options["sdd_creation_authorized"] = sdd_creation_authorized

    try:
        from sase.workspace_provider import materialize_sdd_store as dispatch

        result = dispatch(str(primary), str(workspace), options)
    except Exception as exc:  # noqa: BLE001 - provider failures are user-facing.
        raise SddMaterializationError(str(exc) or type(exc).__name__) from exc

    if _positive_result(result):
        return cast(dict[str, Any], result)

    # Compatibility adapter for provider releases that still split discovery and
    # creation. The authoritative core still fails closed if the adapter cannot
    # return a positive record.
    try:
        from sase.workspace_provider import create_sdd_remote

        compatibility_result = create_sdd_remote(str(primary), str(workspace), options)
    except Exception as exc:  # noqa: BLE001 - provider failures are user-facing.
        raise SddMaterializationError(str(exc) or type(exc).__name__) from exc
    if not _positive_result(compatibility_result):
        raise SddMaterializationError(
            "The provider plugin did not materialize the mandatory companion SDD "
            "repository. Update the provider plugin and rerun `sase sdd init`."
        )
    return cast(dict[str, Any], compatibility_result)


def _provider_options(
    workspace: Path,
    workspace_num: int,
    *,
    policy: SddStorage | None,
    existing_record: SddStoreRecord | None,
) -> dict[str, object]:
    options: dict[str, object] = {
        "workspace_num": workspace_num,
        "provider_policy": policy or "",
        "vcs_name": _detect_vcs_name(workspace) or "",
    }
    if existing_record is not None:
        if existing_record.repo:
            options["sdd_repo"] = existing_record.repo
        if existing_record.host:
            options["sdd_host"] = existing_record.host
        if existing_record.remote_url:
            options["sdd_remote_url"] = existing_record.remote_url
    return options


def _positive_result(result: object) -> bool:
    if not isinstance(result, dict):
        return False
    try:
        return _is_materialized_record(normalize_sdd_store_record(result))
    except (TypeError, ValueError):
        return False


def _refresh_materialized_store(sdd_dir: Path) -> None:
    """Best-effort fast-forward refresh for an existing materialized clone."""

    if not (sdd_dir / ".git").is_dir():
        return
    try:
        from sase.sdd._commit import network_git_timeout

        result = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=sdd_dir,
            capture_output=True,
            text=True,
            timeout=network_git_timeout(),
            check=False,
        )
    except Exception:
        _logger.warning("Failed to refresh materialized SDD store", exc_info=True)
        return
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        _logger.warning(
            "Failed to refresh materialized SDD store in %s: %s",
            sdd_dir,
            detail or f"git pull exited {result.returncode}",
        )


def _ensure_materialized_store_initialized(store: SddStore) -> None:
    """Create generated guides and bead files inside a materialized store."""

    from sase.bead.project import BEADS_DIRNAME_NON_VC, BeadProject
    from sase.sdd._bead_ignore import ensure_bead_store_gitignore
    from sase.sdd._commit import commit_sdd_store_files
    from sase.sdd.files import ensure_sdd_initialized

    sdd_dir = store.sdd_dir
    sdd_dir.mkdir(parents=True, exist_ok=True)
    changed_paths: list[Path] = list(ensure_sdd_initialized(sdd_dir))
    gitignore = ensure_bead_store_gitignore(sdd_dir)
    if gitignore is not None:
        changed_paths.append(gitignore)

    beads_dir = sdd_dir / BEADS_DIRNAME_NON_VC
    if not beads_dir.is_dir():
        with BeadProject.init(sdd_dir, beads_dirname=BEADS_DIRNAME_NON_VC):
            pass
        changed_paths.append(beads_dir)

    if changed_paths:
        commit_sdd_store_files(
            store,
            "Initialize SDD store",
            auto_commit_type="beads",
            paths=changed_paths,
        )
