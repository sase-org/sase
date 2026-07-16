"""Provider dispatch and materialization for remote-backed SDD stores."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import subprocess
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from sase.workspace_provider import SddSidecarPreflight

from sase.sdd._paths import get_primary_workspace_dir
from sase.sdd._store_adoption import (
    adopt_provider_store,
    cleanup_staging,
    clone_matches_record,
    legacy_adoption_needed,
    materialization_lock,
    new_staging_path,
)
from sase.sdd._store_records import (
    delete_sdd_store_record,
    is_materialized_record,
    normalize_sdd_store_record,
    read_sdd_store_record,
    sdd_store_record_path,
    write_sdd_store_record,
)
from sase.sdd._store_resolution import (
    detect_vcs_name,
    provider_sdd_storage_policy,
    resolve_sdd_store,
)
from sase.sdd._store_types import (
    SDD_STORAGE_SEPARATE_REPO,
    SDD_STORAGE_SIDECAR_REPOS,
    SddMaterializationError,
    SddStorage,
    SddStore,
    SddStoreRecord,
)
from sase.sdd._store_workspace import ensure_workspace_sdd_clone

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SddInitOutcome:
    """Result of provider-owned SDD initialization."""

    store: SddStore
    repo: str | None
    remote_url: str | None
    created: bool


def materialize_sdd_store(
    workspace_dir: str | Path,
    workspace_num: int,
    *,
    sdd_creation_authorized: bool | None = None,
) -> SddStore:
    """Materialize the provider-selected store or fail without a local fallback.

    Remote-backed stores require ``is_sase_managed: true`` in the target
    repository's ``sase.yml``. ``sdd_creation_authorized`` is the additional
    explicit-init guard: omitting it authorizes creation for a managed repo,
    while ``False`` still permits discovery but must prevent remote creation.
    """

    store, _created = materialize_sdd_store_with_created(
        workspace_dir,
        workspace_num,
        sdd_creation_authorized=sdd_creation_authorized,
    )
    return store


def preflight_sdd_sidecar(
    workspace_dir: str | Path,
    workspace_num: int,
) -> SddSidecarPreflight:
    """Return authoritative, read-only provider discovery for explicit init."""
    from sase.workspace_provider import (
        SddSidecarPreflight,
        preflight_sdd_sidecar as dispatch,
    )

    workspace = Path(workspace_dir).expanduser()
    primary = Path(
        get_primary_workspace_dir(str(workspace), workspace_num)
    ).expanduser()
    record = read_sdd_store_record(primary)

    options = provider_options(
        workspace,
        workspace_num,
        policy=SDD_STORAGE_SEPARATE_REPO,
        existing_record=(
            cast(SddStoreRecord, record) if is_materialized_record(record) else None
        ),
    )
    try:
        result = dispatch(str(primary), str(workspace), options)
    except Exception as exc:  # noqa: BLE001 - provider failures are user-facing.
        raise SddMaterializationError(str(exc) or type(exc).__name__) from exc
    if not isinstance(result, SddSidecarPreflight):
        raise SddMaterializationError(
            "The workspace provider does not support authoritative SDD sidecar "
            "preflight. Update the provider plugin and rerun `sase repo init`."
        )
    return result


def create_and_materialize_sdd_store(
    workspace_dir: str | Path,
    workspace_num: int,
) -> SddInitOutcome:
    """Compatibility name for the unified provider-owned materialization path."""

    store, created = materialize_sdd_store_with_created(workspace_dir, workspace_num)
    primary = Path(get_primary_workspace_dir(str(Path(workspace_dir)), workspace_num))
    record = read_sdd_store_record(primary)
    return SddInitOutcome(
        store=store,
        repo=record.repo if record else None,
        remote_url=record.remote_url if record else None,
        created=created,
    )


def materialize_sdd_store_with_created(
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

    creation_authorized: bool | None = None
    if is_remote_backed_record(record):
        creation_authorized = resolve_sdd_creation_authorization(
            primary,
            requested=sdd_creation_authorized,
        )

    if is_sidecar_record(record):
        ensure_workspace_sdd_clone(workspace, workspace_num, strict=True)
        return resolve_sdd_store(workspace, workspace_num), False

    if usable_primary_record(
        primary, record
    ) and not primary_record_needs_legacy_adoption(primary, workspace, record):
        return finalize_existing_store(primary, workspace, workspace_num), False

    policy = (
        None
        if is_materialized_record(record)
        else provider_sdd_storage_policy(workspace)
    )
    if policy != SDD_STORAGE_SEPARATE_REPO and not is_materialized_record(record):
        return resolve_sdd_store(workspace, workspace_num), False

    if creation_authorized is None:
        creation_authorized = resolve_sdd_creation_authorization(
            primary,
            requested=sdd_creation_authorized,
        )

    with materialization_lock(primary):
        record = read_sdd_store_record(primary)
        usable_record = usable_primary_record(primary, record)
        if usable_record and not primary_record_needs_legacy_adoption(
            primary, workspace, record
        ):
            return finalize_existing_store(primary, workspace, workspace_num), False

        # Only recognized negative records are stale cache entries. Foreign or
        # malformed records fail while loading, before this replacement path.
        # Positive records remain authoritative until a transaction succeeds.
        if (
            not is_materialized_record(record)
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
                result = provider_materialization_result(
                    primary,
                    workspace,
                    workspace_num,
                    policy=policy,
                    existing_record=(
                        cast(SddStoreRecord, record)
                        if is_materialized_record(record)
                        else None
                    ),
                    staging=staging,
                    sdd_creation_authorized=creation_authorized,
                )
                normalized = normalize_sdd_store_record(result)
                created = bool(result.get("created"))
            if not is_materialized_record(normalized):
                raise SddMaterializationError(
                    "The workspace provider did not create or find the required "
                    "sidecar SDD repository. Update the provider plugin and rerun "
                    "`sase repo init`."
                )
            if not normalized.remote_url:
                raise SddMaterializationError(
                    "The workspace provider returned no sidecar clone URL. Update "
                    "the provider plugin and rerun `sase repo init`."
                )

            adopt_provider_store(primary, workspace, normalized, staging)
            write_sdd_store_record(primary, normalized)
            try:
                ensure_workspace_sdd_clone(workspace, workspace_num, strict=True)
            except Exception:
                delete_sdd_store_record(primary)
                raise

            store = resolve_sdd_store(workspace, workspace_num)
            refresh_materialized_store(store.sdd_dir)
            ensure_materialized_store_initialized(store)
            return resolve_sdd_store(workspace, workspace_num), created
        finally:
            cleanup_staging(staging)


def usable_primary_record(primary: Path, record: SddStoreRecord | None) -> bool:
    return bool(
        is_materialized_record(record)
        and clone_matches_record(
            primary / ".sase" / "sdd", cast(SddStoreRecord, record)
        )
    )


def primary_record_needs_legacy_adoption(
    primary: Path,
    workspace: Path,
    record: SddStoreRecord | None,
) -> bool:
    return bool(
        is_materialized_record(record)
        and legacy_adoption_needed(
            primary,
            workspace,
            cast(SddStoreRecord, record),
        )
    )


def finalize_existing_store(
    primary: Path,
    workspace: Path,
    workspace_num: int,
) -> SddStore:
    ensure_workspace_sdd_clone(workspace, workspace_num, strict=True)
    store = resolve_sdd_store(workspace, workspace_num)
    refresh_materialized_store(store.sdd_dir)
    ensure_materialized_store_initialized(store)
    return resolve_sdd_store(workspace, workspace_num)


def is_sidecar_record(record: SddStoreRecord | None) -> bool:
    return bool(
        is_materialized_record(record)
        and record is not None
        and record.is_sidecar_storage
    )


def is_remote_backed_record(record: SddStoreRecord | None) -> bool:
    return bool(
        is_materialized_record(record)
        and record is not None
        and record.storage in {SDD_STORAGE_SEPARATE_REPO, SDD_STORAGE_SIDECAR_REPOS}
    )


def resolve_sdd_creation_authorization(
    primary: Path,
    *,
    requested: bool | None,
) -> bool:
    """Require repository-local management before any remote SDD use."""

    from sase.project_management import project_management_status
    from sase.content_layout import (
        resolve_project_config_read_path,
        resolve_project_config_write_path,
    )

    config_path = resolve_project_config_read_path(primary)
    if config_path is None:
        config_path = resolve_project_config_write_path(primary)
    management = project_management_status(config_path)
    if management.error is not None:
        raise SddMaterializationError(management.error)
    if not management.is_sase_managed:
        raise SddMaterializationError(
            "SDD materialization refused: repository is not SASE-managed; set "
            "is_sase_managed: true in the target repository's sase/sase.yml to "
            "enable it"
        )
    return requested is not False


def provider_materialization_result(
    primary: Path,
    workspace: Path,
    workspace_num: int,
    *,
    policy: SddStorage | None,
    existing_record: SddStoreRecord | None,
    staging: Path,
    sdd_creation_authorized: bool,
) -> dict[str, Any]:
    options = provider_options(
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
            "sdd_creation_authorized": sdd_creation_authorized,
        }
    )

    try:
        from sase.workspace_provider import materialize_sdd_store as dispatch

        result = dispatch(str(primary), str(workspace), options)
    except Exception as exc:  # noqa: BLE001 - provider failures are user-facing.
        raise SddMaterializationError(str(exc) or type(exc).__name__) from exc

    if is_positive_materialization_result(result):
        return cast(dict[str, Any], result)

    # Compatibility adapter for provider releases that still split discovery and
    # creation. The authoritative core still fails closed if the adapter cannot
    # return a positive record.
    try:
        from sase.workspace_provider import create_sdd_remote

        compatibility_result = create_sdd_remote(str(primary), str(workspace), options)
    except Exception as exc:  # noqa: BLE001 - provider failures are user-facing.
        raise SddMaterializationError(str(exc) or type(exc).__name__) from exc
    if not is_positive_materialization_result(compatibility_result):
        raise SddMaterializationError(
            "The provider plugin did not materialize the mandatory sidecar SDD "
            "repository. Update the provider plugin and rerun `sase repo init`."
        )
    return cast(dict[str, Any], compatibility_result)


def provider_options(
    workspace: Path,
    workspace_num: int,
    *,
    policy: SddStorage | None,
    existing_record: SddStoreRecord | None,
) -> dict[str, object]:
    options: dict[str, object] = {
        "workspace_num": workspace_num,
        "provider_policy": policy or "",
        "vcs_name": detect_vcs_name(workspace) or "",
    }
    if existing_record is not None:
        if existing_record.repo:
            options["sdd_repo"] = existing_record.repo
        if existing_record.host:
            options["sdd_host"] = existing_record.host
        if existing_record.remote_url:
            options["sdd_remote_url"] = existing_record.remote_url
    return options


def is_positive_materialization_result(result: object) -> bool:
    if not isinstance(result, dict):
        return False
    try:
        return is_materialized_record(normalize_sdd_store_record(result))
    except (TypeError, ValueError):
        return False


def refresh_materialized_store(sdd_dir: Path) -> None:
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


def ensure_materialized_store_initialized(store: SddStore) -> None:
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
