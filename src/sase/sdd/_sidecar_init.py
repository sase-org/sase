"""Initialization transactions for configured sidecar repositories."""

from __future__ import annotations

from collections.abc import Sequence
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
) -> _SidecarInitOutcome:
    """Create/adopt, initialize, push, then record configured sidecars."""

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

        from sase.linked_repos import sidecar_repo_clone_dir

        roots = {
            spec.role: Path(sidecar_repo_clone_dir(workspace, spec.role))
            for spec in sidecar_specs
        }
        for spec in sidecar_specs:
            root = roots[spec.role]
            sidecar = sidecars[spec.role]
            ensure_sidecar_sdd_clone(root, sidecar.remote_url, strict=True)
        _seed_sidecars(
            sidecar_specs,
            roots,
            repo_names={role: sidecar.repo for role, sidecar in sidecars.items()},
        )

        record, store = _write_compatibility_store(
            primary,
            roots,
            sidecars,
            existing=existing,
            provider=provider,
            host=host,
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
) -> dict[str, Path]:
    """Refresh configured sidecars already materialized in this workspace.

    This preserves an authoritative sidecar store record when the current VCS
    provider cannot create repositories (for example, a local bare-git clone
    of a project whose sidecars were established through another provider).
    """

    from sase.linked_repos import sidecar_repo_clone_dir

    workspace = Path(workspace_dir).expanduser()
    roots = {
        spec.role: Path(sidecar_repo_clone_dir(workspace, spec.role))
        for spec in sidecar_specs
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
    )
    return roots


def _seed_sidecars(
    sidecar_specs: Sequence[SidecarInitSpec],
    roots: dict[str, Path],
    *,
    repo_names: dict[str, str],
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
        if spec.role == "plans":
            gitignore = ensure_bead_store_gitignore(root)
            if gitignore is not None:
                generated.append(gitignore)
        committed = bool(generated) and commit_sdd_files(
            root,
            f"Initialize SASE {spec.role} sidecar",
            auto_commit_type="init",
            paths=generated,
            repo_name=repo_names[spec.role],
            record_commit_marker=False,
        )
        if committed:
            _push_sidecar(root)


def _existing_compatibility_sidecar(
    existing: SddStoreRecord | None,
    role: str,
) -> SddSidecar | None:
    if role not in SPLIT_SIDECAR_KINDS:
        return None
    if not (
        is_materialized_record(existing)
        and existing is not None
        and existing.is_sidecar_storage
    ):
        return None
    return existing.sidecar_for_kind(role)


def _write_compatibility_store(
    primary: Path,
    roots: dict[str, Path],
    sidecars: dict[str, SddSidecar],
    *,
    existing: SddStoreRecord | None,
    provider: str | None,
    host: str | None,
) -> tuple[SddStoreRecord | None, SddStore | None]:
    existing_plans = _existing_compatibility_sidecar(existing, "plans")
    existing_research = _existing_compatibility_sidecar(existing, "research")
    plans = sidecars.get("plans") or existing_plans
    research = sidecars.get("research") or existing_research
    if plans is None or research is None:
        return None, None

    record = write_sdd_store_record(
        primary,
        SddStoreRecord(
            schema_version=2,
            storage=SDD_STORAGE_SIDECAR_REPOS,
            provider=provider or (existing.provider if existing is not None else None),
            host=host or (existing.host if existing is not None else None),
            discovery="found",
            plans=plans,
            research=research,
        ),
    )
    plans_root = roots.get("plans") or primary / "sase" / "repos" / "plans"
    research_root = roots.get("research") or primary / "sase" / "repos" / "research"
    return (
        record,
        SddStore(
            storage=SDD_STORAGE_SIDECAR_REPOS,
            sdd_dir=plans_root,
            repo_root=plans_root,
            provider=record.provider,
            remote_url=plans.remote_url,
            research_dir=research_root,
            research_remote_url=research.remote_url,
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


def _push_sidecar(root: Path) -> None:
    try:
        # Push does not update the local index, so index.lock recovery is irrelevant.
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
            f"failed to push initialized sidecar {root}: {exc}"
        ) from exc


__all__ = [
    "SidecarInitSpec",
    "initialize_materialized_sidecars",
    "initialize_sidecars",
    "preflight_sidecars",
]
