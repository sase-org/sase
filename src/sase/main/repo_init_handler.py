"""Initialize configured project sidecars and repository-local wiring."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, MutableMapping, MutableSequence
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import TYPE_CHECKING, Any, TextIO

from sase.config import ConfigEditError, set_key
from sase.project_management import ProjectManagementStatus, project_management_status

from .init_plan import InitAction, InitPlan
from .init_project_scope import is_project_directory

if TYPE_CHECKING:
    from sase.sdd._sidecar_init import SidecarInitSpec
    from sase.workspace_provider import SddSidecarPreflight

_NON_PROJECT_REPO_MESSAGE = "sase repo init: not a project directory (no VCS found); skipping repository initialization"
_UNMANAGED_REPO_MESSAGE = (
    "Repository initialization skipped: repository is not SASE-managed; set "
    "is_sase_managed: true in the target repository's sase.yml to enable it"
)
_COMMAND_LABEL = "repo init"


@dataclass(frozen=True)
class _ConfigUpdate:
    path: Path
    current_text: str
    updated_text: str
    error: str | None = None

    @property
    def changed(self) -> bool:
        return self.error is None and self.updated_text != self.current_text


def handle_repo_init_command(args: argparse.Namespace) -> None:
    """Handle ``sase repo init`` and its ``sase init repo`` alias."""

    raise SystemExit(run_repo_init(args))


def run_repo_init(args: argparse.Namespace) -> int:
    """Apply configured sidecar, plans-config, and ignore-rule initialization."""

    if getattr(args, "check", False):
        from .init_onboarding import run_init_check
        from .init_registry import InitCommandSpec

        return run_init_check(
            args,
            specs=(
                InitCommandSpec(
                    name="repo",
                    label="Repos",
                    plan=plan_repo_init,
                    run=run_repo_init,
                ),
            ),
        )

    project_root, management = _repo_project_management(getattr(args, "path", None))
    if not is_project_directory(project_root):
        print(_NON_PROJECT_REPO_MESSAGE, file=sys.stderr)
        return 1
    if management.error is not None:
        print(f"error: {management.error}", file=sys.stderr)
        return 1
    if not management.is_sase_managed:
        print(_UNMANAGED_REPO_MESSAGE)
        return 0

    plan = plan_repo_init(args)
    if plan.blockers:
        for blocker in plan.blockers:
            print(f"error: {blocker}", file=sys.stderr)
        return 1
    if getattr(args, "diff", False):
        from .init_preview import preview_console, render_plan_diff

        render_plan_diff(preview_console(sys.stdout), plan)

    changed_project_paths: list[Path] = []
    config_update = _explicit_plans_config_update(management.config_path)
    if config_update.error is not None:
        print(f"error: {config_update.error}", file=sys.stderr)
        return 1
    if config_update.changed:
        try:
            config_update.path.write_text(config_update.updated_text, encoding="utf-8")
        except OSError as exc:
            print(
                f"error: {config_update.path}: failed to write file: {exc}",
                file=sys.stderr,
            )
            return 1
        changed_project_paths.append(config_update.path)
        print(
            f"{_COMMAND_LABEL}: updated {config_update.path} with repos.sidecar plans"
        )

    try:
        policy = _project_provider_sdd_policy(project_root)
        if policy == "separate_repo":
            exit_code = _run_configured_sidecars(args, project_root)
        elif _has_materialized_sidecar_store(project_root):
            exit_code = _run_materialized_sidecars(project_root)
        else:
            exit_code = _run_legacy_store_init(project_root)
    except Exception as exc:  # noqa: BLE001 - provider and store failures are user-facing.
        from sase.sdd.store import SddMaterializationError

        if isinstance(exc, SddMaterializationError):
            print(f"error: {exc}", file=sys.stderr)
            return 1
        raise
    if exit_code != 0:
        return exit_code

    from .init_workspace_handler import (
        commit_workspace_paths,
        ensure_workspace_gitignore,
        find_git_root,
    )

    changed_gitignore = ensure_workspace_gitignore(project_root)
    if changed_gitignore is not None:
        changed_project_paths.append(changed_gitignore)
        print(f"{_COMMAND_LABEL}: updated {changed_gitignore}")

    if not changed_project_paths or getattr(args, "no_commit", False):
        return 0
    git_root = find_git_root(project_root)
    if git_root is None:
        return 0
    return commit_workspace_paths(
        git_root,
        tuple(dict.fromkeys(changed_project_paths)),
        command_label=_COMMAND_LABEL,
        message="chore: initialize SASE repositories",
    )


def plan_repo_init(args: argparse.Namespace) -> InitPlan:
    """Return a read-only plan for repository and sidecar initialization."""

    project_root, management = _repo_project_management(getattr(args, "path", None))
    if not is_project_directory(project_root):
        return InitPlan(
            command="repo",
            label="Repos",
            summary=_NON_PROJECT_REPO_MESSAGE,
            actions=(),
            blockers=(_NON_PROJECT_REPO_MESSAGE,),
        )
    if management.error is not None:
        return InitPlan(
            command="repo",
            label="Repos",
            summary="cannot determine whether the repository is SASE-managed",
            actions=(),
            blockers=(management.error,),
        )
    if not management.is_sase_managed:
        return InitPlan(
            command="repo",
            label="Repos",
            summary=_UNMANAGED_REPO_MESSAGE,
            actions=(),
            warnings=(_UNMANAGED_REPO_MESSAGE,),
        )

    actions: list[InitAction] = []
    warnings: list[str] = []
    blockers: list[str] = []

    config_update = _explicit_plans_config_update(management.config_path)
    if config_update.error is not None:
        blockers.append(config_update.error)
    elif config_update.changed:
        actions.append(
            InitAction(
                path=config_update.path,
                operation="update" if config_update.path.exists() else "create",
                detail="declare the managed plans sidecar",
                new_content=config_update.updated_text,
            )
        )

    policy = _project_provider_sdd_policy(project_root)
    if policy == "separate_repo" or _has_materialized_sidecar_store(project_root):
        specs = _configured_sidecar_specs(project_root)
        actions.extend(_plan_sidecar_actions(project_root, specs))
    else:
        legacy_actions, legacy_warnings = _plan_legacy_store_actions(project_root)
        actions.extend(legacy_actions)
        warnings.extend(legacy_warnings)

    from .init_workspace_handler import plan_init_workspace

    workspace_args = argparse.Namespace(path=str(project_root))
    actions.extend(plan_init_workspace(workspace_args).actions)

    return InitPlan(
        command="repo",
        label="Repos",
        summary=_summarize_repo_actions(actions),
        actions=tuple(actions),
        warnings=tuple(warnings),
        blockers=tuple(blockers),
    )


def _run_configured_sidecars(args: argparse.Namespace, project_root: Path) -> int:
    from sase.sdd._sidecar_init import initialize_sidecars, preflight_sidecars
    from sase.sdd.store import SddMaterializationError

    specs = _configured_sidecar_specs(project_root)
    authorizations: dict[str, bool] = {}
    for role, preflight in preflight_sidecars(project_root, 1, specs).items():
        if preflight.status == "unavailable":
            detail = preflight.message or (
                f"could not verify {preflight.provider} sidecar repository {preflight.repo}"
            )
            raise SddMaterializationError(detail)
        if preflight.status == "not_found":
            if not _confirm_sidecar_creation(args, preflight):
                return 1
            authorizations[role] = True
        elif preflight.status != "found":
            raise SddMaterializationError(
                "The workspace provider returned an invalid sidecar preflight "
                "result. Update the provider plugin and rerun `sase repo init`."
            )

    outcome = initialize_sidecars(
        project_root,
        1,
        specs,
        creation_authorized=authorizations,
    )
    for spec in specs:
        print(outcome.roots[spec.role] / "README.md")
    return 0


def _run_materialized_sidecars(project_root: Path) -> int:
    from sase.sdd._sidecar_init import initialize_materialized_sidecars
    from sase.linked_repos import sidecar_repo_clone_dir
    from sase.sdd.store import SddMaterializationError

    specs = _configured_sidecar_specs(project_root)
    recorded_roles = _materialized_compatibility_roles(project_root)
    materialized: list[SidecarInitSpec] = []
    for spec in specs:
        root = Path(sidecar_repo_clone_dir(project_root, spec.role))
        if (root / ".git").is_dir():
            materialized.append(spec)
        elif spec.role not in recorded_roles:
            raise SddMaterializationError(
                f"configured {spec.role} sidecar is not materialized at {root}; "
                "rerun `sase repo init` with the repository's workspace provider"
            )
    roots = initialize_materialized_sidecars(project_root, materialized)
    for spec in materialized:
        print(roots[spec.role] / "README.md")
    return 0


def _confirm_sidecar_creation(
    args: argparse.Namespace,
    preflight: SddSidecarPreflight,
) -> bool:
    stdin: TextIO = getattr(args, "_init_stdin", None) or sys.stdin
    resource = f"{preflight.provider} sidecar repository"
    if not stdin.isatty():
        print(
            f"error: {resource} creation cancelled: interactive y/yes confirmation is required",
            file=sys.stderr,
        )
        return False

    input_func = getattr(args, "_init_input_func", None) or input
    prompt = (
        f"Create {preflight.visibility} {preflight.provider} sidecar repository "
        f"{preflight.repo} on {preflight.host}? [y/N] "
    )
    try:
        answer = input_func(prompt)
    except EOFError:
        print(
            f"error: {resource} creation cancelled: no confirmation was received",
            file=sys.stderr,
        )
        return False
    except KeyboardInterrupt:
        print(f"\nerror: {resource} creation cancelled", file=sys.stderr)
        return False
    if answer.strip().lower() in {"y", "yes"}:
        return True
    print(
        f"{resource} creation cancelled; repository initialization is incomplete",
        file=sys.stderr,
    )
    return False


def _run_legacy_store_init(project_root: Path) -> int:
    from sase.sdd.files import ensure_sdd_initialized, expected_sdd_readme
    from sase.sdd.store import materialize_sdd_store

    store = materialize_sdd_store(
        project_root,
        1,
        sdd_creation_authorized=False,
    )
    from sase.sdd._prompt_migration import migrate_legacy_prompt_directories

    migration = migrate_legacy_prompt_directories(store.sdd_dir)
    generated_paths = ensure_sdd_initialized(store.sdd_dir)
    for warning in migration.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if not store.is_in_tree and (migration.moved or migration.changed):
        from sase.sdd.files import commit_sdd_store_files

        commit_sdd_store_files(
            store,
            "Migrate SDD prompts into plan month directories",
            paths=[*migration.moved, *migration.changed, *generated_paths],
        )
    print(expected_sdd_readme(str(store.sdd_dir)).path)
    return 0


def _plan_legacy_store_actions(
    project_root: Path,
) -> tuple[list[InitAction], list[str]]:
    from sase.sdd._prompt_migration import plan_legacy_prompt_migration
    from sase.sdd.files import plan_sdd_init_actions
    from sase.sdd.store import resolve_sdd_dir

    sdd_root = Path(resolve_sdd_dir(project_root, 1))
    actions: list[InitAction] = []
    warnings: list[str] = []
    for migration in plan_legacy_prompt_migration(sdd_root):
        if migration.warning:
            warnings.append(migration.warning)
        if migration.source == migration.destination or migration.new_content is None:
            continue
        actions.append(
            InitAction(
                path=migration.destination,
                operation="create",
                detail=(
                    f"move {migration.source.relative_to(sdd_root).as_posix()} to "
                    f"{migration.destination.relative_to(sdd_root).as_posix()}"
                ),
                new_content=migration.new_content,
            )
        )
    actions.extend(
        InitAction(
            path=action.path,
            operation=action.operation,
            detail=action.detail,
            new_content=action.new_content,
        )
        for action in plan_sdd_init_actions(str(sdd_root))
    )
    return actions, warnings


def _plan_sidecar_actions(
    project_root: Path,
    specs: tuple[SidecarInitSpec, ...],
) -> list[InitAction]:
    from sase.linked_repos import sidecar_repo_clone_dir
    from sase.sdd.files import plan_sdd_sidecar_init_actions

    recorded_roles = _materialized_compatibility_roles(project_root)
    actions: list[InitAction] = []
    for spec in specs:
        root = Path(sidecar_repo_clone_dir(project_root, spec.role))
        clone_exists = (root / ".git").is_dir()
        needs_connection = not clone_exists and spec.role not in recorded_roles
        if needs_connection:
            actions.append(
                InitAction(
                    path=root,
                    operation="create",
                    detail=f"create or connect the provider {spec.role} sidecar repository",
                )
            )
        if clone_exists or needs_connection:
            actions.extend(
                InitAction(
                    path=action.path,
                    operation=action.operation,
                    detail=action.detail,
                    new_content=action.new_content,
                )
                for action in plan_sdd_sidecar_init_actions(
                    spec.role,
                    root,
                    description=spec.description,
                )
            )
    return actions


def _configured_sidecar_specs(project_root: Path) -> tuple[SidecarInitSpec, ...]:
    from sase._linked_repo_config import (
        _DEFAULT_LINKED_REPO_MARKER,
        _SIDECAR_REPO_REF_KEY,
        _SIDECAR_ROLE_KEY,
        full_github_repo_name,
        inject_default_linked_repos,
        merged_sidecar_entries_from_config,
        read_project_local_config,
        resolution_config,
    )
    from sase.sdd._sidecar_init import SidecarInitSpec

    primary = project_root.expanduser().resolve(strict=False)
    config = resolution_config(str(primary), None)
    entries = merged_sidecar_entries_from_config(
        config,
        primary_workspace_dir=str(primary),
    )
    entries = inject_default_linked_repos(
        entries,
        primary_workspace_dir=str(primary),
        local_config=read_project_local_config(str(primary)),
    )

    specs: list[SidecarInitSpec] = []
    for entry in entries:
        if entry.get("disabled") is True:
            continue
        role = _entry_text(entry, _SIDECAR_ROLE_KEY) or _entry_text(entry, "name")
        if not role:
            continue
        raw_repo = _entry_text(entry, "repo")
        repo: str | None = None
        if raw_repo:
            repo = full_github_repo_name(primary, raw_repo) or raw_repo
        elif entry.get(_DEFAULT_LINKED_REPO_MARKER) is not True:
            resolved_repo = _entry_text(entry, _SIDECAR_REPO_REF_KEY)
            if "/" in resolved_repo:
                repo = resolved_repo
        visibility = _entry_text(entry, "visibility") or "public"
        specs.append(
            SidecarInitSpec(
                role=role,
                repo=repo,
                visibility=visibility,
                description=_entry_text(entry, "description") or None,
            )
        )
    return tuple(specs)


def _entry_text(entry: Mapping[str, Any], key: str) -> str:
    value = entry.get(key)
    return value.strip() if isinstance(value, str) else ""


def _explicit_plans_config_update(config_path: Path) -> _ConfigUpdate:
    try:
        current_text = (
            config_path.read_text(encoding="utf-8") if config_path.exists() else ""
        )
    except OSError as exc:
        return _ConfigUpdate(
            config_path, "", "", f"{config_path}: failed to read file: {exc}"
        )

    try:
        from ruamel.yaml.comments import CommentedMap, CommentedSeq

        from sase.config._edit_yaml_io import dump_yaml, make_yaml

        handler = make_yaml()
        data = handler.load(current_text) if current_text.strip() else CommentedMap()
        if not isinstance(data, MutableMapping):
            return _ConfigUpdate(
                config_path,
                current_text,
                current_text,
                f"{config_path}: expected a YAML mapping at the top level",
            )
        repos = data.get("repos")
        if repos is not None and not isinstance(repos, MutableMapping):
            return _ConfigUpdate(
                config_path,
                current_text,
                current_text,
                f"{config_path}: repos must be a YAML mapping",
            )
        sidecars = repos.get("sidecar") if isinstance(repos, MutableMapping) else None
        if sidecars is not None and not isinstance(sidecars, MutableSequence):
            return _ConfigUpdate(
                config_path,
                current_text,
                current_text,
                f"{config_path}: repos.sidecar must be a YAML list",
            )
        if sidecars is not None and any(
            isinstance(entry, Mapping) and _entry_text(entry, "name") == "plans"
            for entry in sidecars
        ):
            return _ConfigUpdate(config_path, current_text, current_text)

        plans_entry = CommentedMap((("name", "plans"), ("auto_clone", True)))
        if sidecars is None:
            updated_text = set_key(
                current_text,
                ("repos", "sidecar"),
                CommentedSeq((plans_entry,)),
            )
        else:
            sidecars.append(plans_entry)
            updated_text = dump_yaml(handler, data)
    except (ConfigEditError, OSError, ValueError) as exc:
        return _ConfigUpdate(
            config_path,
            current_text,
            current_text,
            f"{config_path}: failed to update repos.sidecar: {exc}",
        )
    return _ConfigUpdate(config_path, current_text, updated_text)


def _repo_project_management(
    path: str | Path | None,
) -> tuple[Path, ProjectManagementStatus]:
    project_root = _resolve_project_root(path)
    config_path = project_root / "sase.yml"
    return project_root, project_management_status(config_path)


def _resolve_project_root(path: str | Path | None) -> Path:
    candidate = Path.cwd() if path is None else Path(path).expanduser()
    candidate = candidate.resolve(strict=False)
    if candidate.name == "sase.yml":
        candidate = candidate.parent
    if candidate.name == "sdd" and candidate.parent.name == ".sase":
        candidate = candidate.parent.parent
    if candidate.is_file():
        candidate = candidate.parent
    for root in (candidate, *candidate.parents):
        if (root / ".git").exists():
            return root
    return candidate


def _project_provider_sdd_policy(project_root: Path) -> str | None:
    try:
        from sase.vcs_provider import detect_vcs
        from sase.workspace_provider import get_sdd_storage_policy_by_vcs

        vcs_name = detect_vcs(str(project_root))
        if vcs_name is None:
            return None
        policy = get_sdd_storage_policy_by_vcs(vcs_name)
    except Exception:
        return None
    return policy if policy in {"in_tree", "local", "separate_repo"} else None


def _has_materialized_sidecar_store(project_root: Path) -> bool:
    return bool(_materialized_compatibility_roles(project_root))


def _materialized_compatibility_roles(project_root: Path) -> frozenset[str]:
    try:
        from sase.sdd._paths import get_primary_workspace_dir
        from sase.sdd.store import read_sdd_store_record

        primary = Path(get_primary_workspace_dir(str(project_root), 1))
        record = read_sdd_store_record(primary)
    except (OSError, RuntimeError, ValueError):
        return frozenset()
    if record is None or not record.is_sidecar_storage:
        return frozenset()
    return frozenset(
        role for role in ("plans", "research") if record.sidecar_for_kind(role)
    )


def _summarize_repo_actions(actions: list[InitAction]) -> str:
    if not actions:
        return "configured sidecars, project repo config, and ignore rules are current"
    details = " ".join(action.detail.casefold() for action in actions)
    parts: list[str] = []
    if "sidecar repository" in details:
        parts.append("create or connect configured sidecar repositories")
    if any(action.path.name == "README.md" for action in actions):
        parts.append("refresh sidecar guide files")
    if any(action.path.name == "sase.yml" for action in actions):
        parts.append("declare the plans sidecar")
    if any(action.path.name == ".gitignore" for action in actions):
        parts.append("update repository ignore rules")
    if not parts:
        return f"apply {len(actions)} repository initialization actions"
    if len(parts) == 1:
        return parts[0]
    return f"{', '.join(parts[:-1])} and {parts[-1]}"


__all__ = [
    "handle_repo_init_command",
    "plan_repo_init",
    "run_repo_init",
]
