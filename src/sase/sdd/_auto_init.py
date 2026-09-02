"""Connect-only SDD store auto-init for a project's first launch on a machine."""

from __future__ import annotations

from pathlib import Path
import sys

from sase.sdd._paths import get_primary_workspace_dir
from sase.sdd._store_records import is_materialized_record, read_sdd_store_record
from sase.sdd._store_resolution import provider_sdd_storage_policy
from sase.sdd._store_types import (
    SDD_STORAGE_SEPARATE_REPO,
    SDD_STORAGE_SIDECAR_REPOS,
    SddMaterializationError,
)

__all__ = ["auto_connect_sdd_store"]


def auto_connect_sdd_store(workspace_dir: str | Path, workspace_num: int) -> bool:
    """Connect this machine to the project's existing SDD store, creating nothing.

    Returns True when a store record is materialized (pre-existing or newly
    connected). Returns False (no-op) when the project is not sase-managed, is
    not a project directory, or the provider policy is not remote-backed.
    Raises SddMaterializationError with a `sase repo init` remedy when a
    required sidecar repository does not exist remotely.
    """

    primary = Path(
        get_primary_workspace_dir(str(Path(workspace_dir).expanduser()), workspace_num)
    ).expanduser()

    if is_materialized_record(read_sdd_store_record(primary)):
        return True

    from sase.main._repo_init_config import (
        configured_sidecar_specs,
        repo_project_management,
    )
    from sase.main.init_project_scope import is_project_directory

    project_root, management = repo_project_management(primary)
    if not is_project_directory(project_root):
        return False
    if management.error is not None or not management.is_sase_managed:
        return False

    policy = provider_sdd_storage_policy(project_root)
    if policy not in {SDD_STORAGE_SEPARATE_REPO, SDD_STORAGE_SIDECAR_REPOS}:
        return False

    from sase._linked_repo_config import AGENTS_SIDECAR_ROLE
    from sase.sdd._sidecar_init import initialize_sidecars, preflight_sidecars

    specs = configured_sidecar_specs(project_root)
    if not specs:
        return False

    preflights = preflight_sidecars(project_root, 1, specs)
    for preflight in preflights.values():
        if preflight.status == "unavailable":
            raise SddMaterializationError(
                preflight.message
                or (
                    "could not verify "
                    f"{preflight.provider} sidecar repository {preflight.repo}"
                )
            )
        if preflight.status not in {"found", "not_found"}:
            raise SddMaterializationError(
                "The workspace provider returned an invalid sidecar preflight "
                "result. Update the provider plugin and rerun `sase repo init`."
            )

    selected_roles = {spec.role for spec in specs}
    for role, preflight in preflights.items():
        if preflight.status != "not_found":
            continue
        if role == AGENTS_SIDECAR_ROLE:
            selected_roles.discard(role)
            print(
                f"warning: {preflight.provider} sidecar repository "
                f"{preflight.repo} is missing; run `sase repo init` "
                "interactively to create it",
                file=sys.stderr,
            )
            continue
        raise SddMaterializationError(
            f"{preflight.provider} sidecar repository {preflight.repo} does "
            f"not exist; run `sase repo init` in {project_root} to create it"
        )

    selected_specs = tuple(spec for spec in specs if spec.role in selected_roles)
    if not selected_specs:
        return False

    initialize_sidecars(
        project_root,
        1,
        selected_specs,
        creation_authorized={},
        publish_sidecar_changes=True,
    )
    return True
