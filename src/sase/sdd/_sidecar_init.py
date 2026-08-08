"""Initialization transactions for configured sidecar repositories."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from sase.sdd._bead_adoption import (
    AdoptionOutcome,
    adopt_bead_state,
    cleanup_plans_bead_state,
)
from sase.sdd._bead_ignore import ensure_bead_store_gitignore
from sase.sdd._commit import commit_sdd_files
from sase.sdd._init_files import ensure_sdd_sidecar_initialized
from sase.sdd._paths import get_primary_workspace_dir
from sase.sdd._sidecar_git import push_sidecar
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


@dataclass(frozen=True)
class SidecarInitSpec:
    """Provider and seed controls for one enabled configured sidecar."""

    role: str
    repo: str | None = None
    remote_url: str | None = None
    visibility: str = "public"
    description: str | None = None


@dataclass(frozen=True)
class _SidecarInitOutcome:
    """Completed configured-sidecar initialization transaction."""

    store: SddStore | None
    record: SddStoreRecord | None
    created: frozenset[str]
    roots: dict[str, Path]


def unresolved_project_key_message(workspace_dir: str | Path) -> str:
    """Describe an agents sidecar whose owning SASE project key is unknown."""

    workspace = Path(workspace_dir).expanduser()
    return (
        "could not resolve the owning SASE project key for the agents "
        f"sidecar from {workspace}"
    )


def resolve_sidecar_clone_root(workspace_dir: str | Path, role: str) -> Path | None:
    """Resolve one sidecar storage root, or ``None`` without a project key.

    Only the unresolvable-project-key case degrades to ``None``; every other
    failure still raises :class:`SddMaterializationError`.
    """

    from sase._linked_repo_config import AGENTS_SIDECAR_ROLE
    from sase.linked_repos import hidden_sidecar_clone_dir, sidecar_repo_clone_dir

    workspace = Path(workspace_dir).expanduser()
    if role != AGENTS_SIDECAR_ROLE:
        return Path(sidecar_repo_clone_dir(workspace, role))

    from sase.bead.project_name import infer_project_name_from_cwd

    project_key = infer_project_name_from_cwd(str(workspace))
    if not project_key:
        return None
    try:
        return Path(hidden_sidecar_clone_dir(project_key, role))
    except ValueError as exc:
        raise SddMaterializationError(
            f"could not resolve the agents sidecar clone path: {exc}"
        ) from exc


def sidecar_clone_root(workspace_dir: str | Path, role: str) -> Path:
    """Resolve the storage root for one configured sidecar role."""

    root = resolve_sidecar_clone_root(workspace_dir, role)
    if root is None:
        raise SddMaterializationError(unresolved_project_key_message(workspace_dir))
    return root


def preflight_sidecars(
    workspace_dir: str | Path,
    workspace_num: int,
    sidecars: Sequence[SidecarInitSpec],
) -> dict[str, SddSidecarPreflight]:
    """Discover configured sidecars without mutating local or remote state."""

    from sase.workspace_provider import (
        SddSidecarPreflight,
        preflight_sdd_sidecar,
    )

    workspace = Path(workspace_dir).expanduser()
    primary = Path(
        get_primary_workspace_dir(str(workspace), workspace_num)
    ).expanduser()
    results: dict[str, SddSidecarPreflight] = {}
    for sidecar in sidecars:
        try:
            result = preflight_sdd_sidecar(
                str(primary),
                str(workspace),
                _sidecar_provider_options(workspace_num, sidecar),
            )
        except Exception as exc:  # noqa: BLE001 - provider errors are user-facing.
            raise SddMaterializationError(str(exc) or type(exc).__name__) from exc
        if not isinstance(result, SddSidecarPreflight):
            raise SddMaterializationError(
                "The workspace provider does not support configured sidecar "
                "preflight. Update the provider plugin and rerun `sase repo init`."
            )
        if (
            result.status == "not_found"
            and result.visibility.casefold() != sidecar.visibility.casefold()
        ):
            raise SddMaterializationError(
                f"The {result.provider} provider would create {result.repo} with "
                f"{result.visibility} visibility, but repos.sidecar config requires "
                f"{sidecar.visibility}. Update the provider plugin and rerun "
                "`sase repo init`."
            )
        results[sidecar.role] = result
    return results


def initialize_sidecars(
    workspace_dir: str | Path,
    workspace_num: int,
    sidecar_specs: Sequence[SidecarInitSpec],
    *,
    creation_authorized: dict[str, bool] | None = None,
    publish_sidecar_changes: bool = True,
) -> _SidecarInitOutcome:
    """Create/adopt, initialize, push, then record configured sidecars."""

    workspace = Path(workspace_dir).expanduser()
    primary = Path(
        get_primary_workspace_dir(str(workspace), workspace_num)
    ).expanduser()
    authorizations = creation_authorized or {}
    roots = {
        spec.role: sidecar_clone_root(workspace, spec.role) for spec in sidecar_specs
    }

    with materialization_lock(primary):
        existing = read_sdd_store_record(primary)
        sidecars: dict[str, SddSidecar] = {}
        provider: str | None = None
        host: str | None = None
        created: set[str] = set()

        for spec in sidecar_specs:
            existing_sidecar = _existing_compatibility_sidecar(existing, spec.role)
            result = _create_or_adopt_sidecar(
                primary,
                workspace,
                workspace_num,
                spec,
                existing_sidecar=existing_sidecar,
                creation_authorized=authorizations.get(spec.role, False),
            )
            sidecars[spec.role] = SddSidecar(
                repo=cast(str, result.repo),
                remote_url=cast(str, result.remote_url),
            )
            provider = provider or result.provider
            host = host or result.host
            if result.created:
                created.add(spec.role)

        for spec in sidecar_specs:
            root = roots[spec.role]
            sidecar = sidecars[spec.role]
            ensure_sidecar_sdd_clone(root, sidecar.remote_url, strict=True)
        _seed_sidecars(
            sidecar_specs,
            roots,
            repo_names={role: sidecar.repo for role, sidecar in sidecars.items()},
            split_beads=bool(existing and existing.has_split_beads),
            publish_changes=publish_sidecar_changes,
        )

        combined_sidecars = (
            dict(existing.sidecars)
            if existing is not None and existing.is_sidecar_storage
            else {}
        )
        combined_sidecars.update(sidecars)
        plans = combined_sidecars.get("plans")
        beads = combined_sidecars.get("beads")
        plans_root = roots.get("plans") or primary / "sase" / "repos" / "plans"
        beads_root = roots.get("beads") or primary / "sase" / "repos" / "beads"
        should_adopt = "beads" in sidecars and plans is not None and beads is not None
        adoption: AdoptionOutcome | None = None
        if should_adopt:
            assert plans is not None
            adoption = adopt_bead_state(
                plans_root,
                beads_root,
                plans_repo=plans.repo,
                publish_changes=publish_sidecar_changes,
            )

        record, store = _write_compatibility_store(
            primary,
            workspace,
            roots,
            sidecars,
            existing=existing,
            provider=provider,
            host=host,
        )
        if adoption is not None and record is not None and record.has_split_beads:
            cleanup_plans_bead_state(
                plans_root,
                publish_changes=publish_sidecar_changes,
            )
        return _SidecarInitOutcome(
            store=store,
            record=record,
            created=frozenset(created),
            roots=roots,
        )


def initialize_materialized_sidecars(
    workspace_dir: str | Path,
    sidecar_specs: Sequence[SidecarInitSpec],
    *,
    publish_sidecar_changes: bool = True,
) -> dict[str, Path]:
    """Refresh configured sidecars already materialized in this workspace.

    This preserves an authoritative sidecar store record when the current VCS
    provider cannot create repositories (for example, a local bare-git clone
    of a project whose sidecars were established through another provider).
    """

    workspace = Path(workspace_dir).expanduser()
    roots = {
        spec.role: sidecar_clone_root(workspace, spec.role) for spec in sidecar_specs
    }
    for role, root in roots.items():
        if not (root / ".git").is_dir():
            raise SddMaterializationError(
                f"configured {role} sidecar is not materialized at {root}; "
                "rerun `sase repo init` with the repository's workspace provider"
            )
    _seed_sidecars(
        sidecar_specs,
        roots,
        repo_names={spec.role: spec.repo or spec.role for spec in sidecar_specs},
        split_beads=bool(
            (existing := read_sdd_store_record(workspace)) and existing.has_split_beads
        ),
        publish_changes=publish_sidecar_changes,
    )
    return roots


def _seed_sidecars(
    sidecar_specs: Sequence[SidecarInitSpec],
    roots: dict[str, Path],
    *,
    repo_names: dict[str, str],
    split_beads: bool = False,
    publish_changes: bool = True,
) -> None:
    for spec in sidecar_specs:
        root = roots[spec.role]
        generated = list(
            ensure_sdd_sidecar_initialized(
                spec.role,
                root,
                description=spec.description,
            )
        )
        if spec.role == "plans" and not split_beads:
            gitignore = ensure_bead_store_gitignore(root, prefix="beads")
            if gitignore is not None:
                generated.append(gitignore)
        elif spec.role == "beads":
            gitignore = ensure_bead_store_gitignore(root, prefix="")
            if gitignore is not None:
                generated.append(gitignore)
        committed = (
            publish_changes
            and bool(generated)
            and commit_sdd_files(
                root,
                f"Initialize SASE {spec.role} sidecar",
                auto_commit_type="init",
                paths=generated,
                repo_name=repo_names[spec.role],
                record_commit_marker=False,
            )
        )
        if committed:
            push_sidecar(root)


def _existing_compatibility_sidecar(
    existing: SddStoreRecord | None,
    role: str,
) -> SddSidecar | None:
    if not (
        is_materialized_record(existing)
        and existing is not None
        and existing.is_sidecar_storage
    ):
        return None
    return existing.sidecar_for_kind(role)


def _write_compatibility_store(
    primary: Path,
    workspace: Path,
    roots: dict[str, Path],
    sidecars: dict[str, SddSidecar],
    *,
    existing: SddStoreRecord | None,
    provider: str | None,
    host: str | None,
) -> tuple[SddStoreRecord | None, SddStore | None]:
    combined_sidecars = (
        dict(existing.sidecars)
        if existing is not None and existing.is_sidecar_storage
        else {}
    )
    combined_sidecars.update(sidecars)
    plans = combined_sidecars.get("plans")
    beads = combined_sidecars.get("beads")
    if plans is None:
        return None, None

    record = write_sdd_store_record(
        primary,
        SddStoreRecord(
            schema_version=3 if beads is not None else 2,
            storage=SDD_STORAGE_SIDECAR_REPOS,
            provider=provider or (existing.provider if existing is not None else None),
            host=host or (existing.host if existing is not None else None),
            discovery="found",
            sidecars=combined_sidecars,
        ),
    )
    plans_root = roots.get("plans") or primary / "sase" / "repos" / "plans"
    beads_root = (
        roots.get("beads") or primary / "sase" / "repos" / "beads"
        if beads is not None
        else None
    )
    sidecar_dirs = {
        role: roots.get(role) or sidecar_clone_root(workspace, role)
        for role in combined_sidecars
        if role not in {"plans", "beads"}
    }
    sidecar_remote_urls = {
        role: sidecar.remote_url
        for role, sidecar in combined_sidecars.items()
        if role not in {"plans", "beads"}
    }
    return (
        record,
        SddStore(
            storage=SDD_STORAGE_SIDECAR_REPOS,
            sdd_dir=plans_root,
            repo_root=plans_root,
            provider=record.provider,
            remote_url=plans.remote_url,
            sidecar_dirs=sidecar_dirs,
            sidecar_remote_urls=sidecar_remote_urls,
            beads_dir=beads_root,
            beads_remote_url=beads.remote_url if beads is not None else None,
        ),
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
    spec: SidecarInitSpec,
    *,
    existing_sidecar: SddSidecar | None,
    creation_authorized: bool,
) -> _ProviderSidecar:
    from sase.workspace_provider import create_sdd_remote

    options = _sidecar_provider_options(workspace_num, spec)
    options.update(
        {
            "create": True,
            "sdd_creation_authorized": creation_authorized,
        }
    )
    if existing_sidecar is not None:
        resolved_repo = options.get("sdd_repo")
        if not isinstance(resolved_repo, str) or not resolved_repo.strip():
            options["sdd_repo"] = existing_sidecar.repo
            options.setdefault("sdd_remote_url", existing_sidecar.remote_url)
        elif _repo_refs_match(resolved_repo, existing_sidecar.repo):
            options.setdefault("sdd_remote_url", existing_sidecar.remote_url)
    try:
        raw = create_sdd_remote(str(primary), str(workspace), options)
        normalized = normalize_sdd_store_record(cast(dict[str, object], raw))
    except Exception as exc:  # noqa: BLE001 - provider errors are user-facing.
        raise SddMaterializationError(str(exc) or type(exc).__name__) from exc
    if normalized.storage != SDD_STORAGE_SEPARATE_REPO:
        raise SddMaterializationError(
            f"provider returned invalid {spec.role} sidecar storage metadata"
        )
    if not normalized.repo or not normalized.remote_url:
        raise SddMaterializationError(
            f"provider returned incomplete {spec.role} sidecar metadata"
        )
    created = bool(isinstance(raw, dict) and raw.get("created"))
    return _ProviderSidecar(
        repo=normalized.repo,
        remote_url=normalized.remote_url,
        provider=normalized.provider,
        host=normalized.host,
        created=created,
    )


def _repo_refs_match(left: str, right: str) -> bool:
    def normalize(value: str) -> str:
        normalized = value.strip().strip("/")
        if normalized.endswith(".git"):
            normalized = normalized[: -len(".git")]
        return normalized.casefold()

    return normalize(left) == normalize(right)


def _sidecar_provider_options(
    workspace_num: int,
    sidecar: SidecarInitSpec,
) -> dict[str, object]:
    options: dict[str, object] = {
        "create": False,
        "provider_policy": SDD_STORAGE_SEPARATE_REPO,
        "sdd_sidecar_suffix": sidecar.role,
        "sdd_visibility": sidecar.visibility,
        "workspace_num": workspace_num,
    }
    if sidecar.repo:
        options["sdd_repo"] = sidecar.repo
    if sidecar.remote_url:
        options["sdd_remote_url"] = sidecar.remote_url
    if sidecar.description:
        options["sdd_description"] = sidecar.description
    return options


__all__ = [
    "SidecarInitSpec",
    "initialize_materialized_sidecars",
    "initialize_sidecars",
    "preflight_sidecars",
    "resolve_sidecar_clone_root",
    "sidecar_clone_root",
    "unresolved_project_key_message",
]
