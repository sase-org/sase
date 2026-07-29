"""LSP catalog assembly for kind-tagged artifact references."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any


def build_artifact_ref_lsp_catalog_payload(
    launch_workspace: str | Path | None,
    *,
    artifact_ref_context_fn: Callable[..., Any],
    effective_project_name_fn: Callable[[Any], str],
    list_project_records_fn: Callable[..., list[Any]],
    projects_root: Path,
    schema_version: int,
    workspace_context_fn: Callable[[Path], tuple[Path, int]],
    workspace_project_ref_fn: Callable[[Path], str | None],
) -> dict[str, object]:
    """Build the best-effort local artifact-reference catalog for ``sase lsp``."""

    try:
        project_records = list_project_records_fn(
            projects_root,
            ("enabled",),
            include_home=False,
            projects_only=True,
        )
    except Exception:
        project_records = []

    projects: list[dict[str, object]] = []
    workspace_identities: list[tuple[Path, set[str]]] = []
    seen_keys: set[str] = set()
    ordered_records = sorted(
        (
            record
            for record in project_records
            if not record.system_managed and record.workspace_dir
        ),
        key=lambda record: (
            effective_project_name_fn(record).casefold(),
            record.project_name.casefold(),
        ),
    )
    for record in ordered_records:
        if record.project_name in seen_keys:
            continue
        primary_workspace = record.workspace_dir
        if primary_workspace is None:
            continue
        try:
            workspace_dir, workspace_num = workspace_context_fn(Path(primary_workspace))
            if not workspace_dir.is_dir():
                continue
            context = artifact_ref_context_fn(
                workspace_dir,
                workspace_num,
                project=record.project_name,
            )
            identity = next(
                (
                    project
                    for project in context.projects
                    if project.key == record.project_name
                ),
                None,
            )
            display_name = (
                identity.name
                if identity is not None
                else effective_project_name_fn(record)
            )
            aliases = tuple(
                dict.fromkeys(
                    identity.aliases if identity is not None else record.aliases
                )
            )
            projects.append(
                {
                    "name": display_name,
                    "key": record.project_name,
                    "aliases": list(aliases),
                    "context": context.to_wire(),
                }
            )
            identities = _artifact_ref_project_identities(
                display_name,
                record.project_name,
                aliases,
            )
            workspace_identities.append((workspace_dir, identities))
            seen_keys.add(record.project_name)
        except Exception:
            continue

    launch = Path(launch_workspace or Path.cwd()).expanduser().resolve(strict=False)
    launch_ref = workspace_project_ref_fn(launch)
    default_project: str | None = None
    for (workspace_dir, identities), project in zip(
        workspace_identities,
        projects,
        strict=True,
    ):
        if (
            launch_ref is not None and launch_ref.casefold() in identities
        ) or launch == workspace_dir:
            default_project = str(project["key"])
            break

    return {
        "schema_version": schema_version,
        "default_project": default_project,
        "projects": projects,
    }


def _artifact_ref_project_identities(
    display_name: str,
    project_key: str,
    aliases: tuple[str, ...],
) -> set[str]:
    identities = {
        value.casefold() for value in (display_name, project_key, *aliases) if value
    }
    if project_key.startswith("gh_") and "__" in project_key:
        owner, repository = project_key.removeprefix("gh_").split("__", 1)
        if owner and repository:
            identities.add(f"{owner}/{repository}".casefold())
    return identities


__all__ = ["build_artifact_ref_lsp_catalog_payload"]
