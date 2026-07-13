"""Handler for ``sase sdd`` subcommands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import TYPE_CHECKING, Any, TextIO

from sase.project_management import ProjectManagementStatus, project_management_status

from .init_plan import InitAction, InitPlan
from .init_project_scope import is_project_directory

if TYPE_CHECKING:
    from sase.workspace_provider import SddSidecarPreflight

_NON_PROJECT_SDD_MESSAGE = (
    "sase init sdd: not a project directory (no VCS found); skipping SDD initialization"
)
_UNMANAGED_SDD_MESSAGE = (
    "SDD initialization skipped: repository is not SASE-managed; set "
    "is_sase_managed: true in the target repository's sase.yml to enable it"
)


def handle_sdd_command(args: argparse.Namespace) -> None:
    subcommand = getattr(args, "sdd_subcommand", None)
    if subcommand == "init":
        _handle_init(args)
    elif subcommand == "migrate":
        _handle_migrate(args)
    elif subcommand == "validate":
        _handle_validate(args)
    elif subcommand == "links":
        _handle_links(args)
    elif subcommand == "list":
        _handle_list(args)
    elif subcommand == "path":
        _handle_path(args)
    elif subcommand == "repair-links":
        _handle_repair_links(args)
    else:
        print("Usage: sase sdd {init,links,list,migrate,path,repair-links,validate}")
        sys.exit(1)


def _handle_init(args: argparse.Namespace) -> None:
    sys.exit(run_sdd_init(args))


def _handle_migrate(args: argparse.Namespace) -> None:
    from sase.sdd.migrate import (
        apply_split_sdd_migration,
        plan_split_sdd_migration,
        render_split_sdd_migration_diff,
    )
    from sase.sdd.store import SddMaterializationError

    project_root, management = _sdd_project_management(getattr(args, "path", None))
    if management.error is not None:
        print(f"error: {management.error}", file=sys.stderr)
        sys.exit(1)
    if not management.is_sase_managed:
        print(_UNMANAGED_SDD_MESSAGE, file=sys.stderr)
        sys.exit(1)
    try:
        plan = plan_split_sdd_migration(project_root, 1)
        if getattr(args, "diff", False):
            rendered = render_split_sdd_migration_diff(plan)
            if rendered:
                print(rendered)
        if getattr(args, "check", False):
            if plan.has_changes:
                print(
                    f"SDD split migration required: {len(plan.actions)} files; "
                    f"legacy clone {plan.legacy_root}"
                )
                sys.exit(1)
            print("SDD split migration is current")
            sys.exit(0)
        applied = apply_split_sdd_migration(project_root, 1)
    except SddMaterializationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
    if applied.legacy_root is None:
        print("SDD split migration is current")
    else:
        print(
            f"Migrated {len(applied.actions)} files and retired {applied.legacy_root}"
        )
    sys.exit(0)


def run_sdd_init(args: argparse.Namespace) -> int:
    """Materialize provider storage, refresh generated files, and return code."""
    if getattr(args, "check", False):
        from .init_onboarding import run_init_check
        from .init_registry import InitCommandSpec

        return run_init_check(
            args,
            specs=(
                InitCommandSpec(
                    name="sdd",
                    label="SDD",
                    plan=plan_sdd_init,
                    run=run_sdd_init,
                ),
            ),
        )

    path = getattr(args, "path", None)
    project_root, management = _sdd_project_management(path)
    if not is_project_directory(project_root):
        print(_NON_PROJECT_SDD_MESSAGE, file=sys.stderr)
        return 1
    if management.error is not None:
        print(f"error: {management.error}", file=sys.stderr)
        return 1
    if not management.is_sase_managed:
        print(_UNMANAGED_SDD_MESSAGE)
        return 0

    if getattr(args, "diff", False):
        from .init_preview import preview_console, render_plan_diff

        render_plan_diff(preview_console(sys.stdout), plan_sdd_init(args))

    from sase.sdd.files import ensure_sdd_initialized, expected_sdd_readme
    from sase.sdd.store import (
        SddMaterializationError,
        materialize_sdd_store,
    )

    # Every explicit init starts guarded. This also fails closed if provider
    # policy detection is transiently unavailable here but succeeds later in
    # the materializer.
    creation_authorized = False
    try:
        if _project_provider_sdd_policy(project_root) == "separate_repo":
            from sase.sdd._sidecar_init import (
                initialize_split_sdd_sidecars,
                preflight_split_sdd_sidecars,
            )

            authorizations: dict[str, bool] = {}
            if _split_sidecar_provider_setup_needed(project_root):
                for kind, preflight in preflight_split_sdd_sidecars(
                    project_root, 1
                ).items():
                    if preflight.status == "unavailable":
                        detail = preflight.message or (
                            f"could not verify {preflight.provider} SDD sidecar "
                            f"repository {preflight.repo}"
                        )
                        raise SddMaterializationError(detail)
                    if preflight.status == "not_found":
                        if not _confirm_sdd_sidecar_creation(args, preflight):
                            return 1
                        authorizations[kind] = True
                    elif preflight.status != "found":
                        raise SddMaterializationError(
                            "The workspace provider returned an invalid SDD sidecar "
                            "preflight result. Update the provider plugin and rerun "
                            "`sase sdd init`."
                        )

            outcome = initialize_split_sdd_sidecars(
                project_root,
                1,
                creation_authorized=authorizations,
            )
            print(outcome.store.sdd_dir / "README.md")
            assert outcome.store.research_dir is not None
            print(outcome.store.research_dir / "README.md")
            return 0

        store = materialize_sdd_store(
            project_root,
            1,
            sdd_creation_authorized=creation_authorized,
        )
    except SddMaterializationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

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
    readme_path = expected_sdd_readme(str(store.sdd_dir)).path
    print(readme_path)
    return 0


def _confirm_sdd_sidecar_creation(
    args: argparse.Namespace,
    preflight: SddSidecarPreflight,
) -> bool:
    stdin: TextIO = getattr(args, "_init_stdin", None) or sys.stdin
    resource = f"{preflight.provider} SDD sidecar repository"
    if not stdin.isatty():
        print(
            f"error: {resource} creation cancelled: "
            "interactive y/yes confirmation is required",
            file=sys.stderr,
        )
        return False

    input_func = getattr(args, "_init_input_func", None) or input
    prompt = (
        f"Create {preflight.visibility} {preflight.provider} SDD sidecar "
        f"repository {preflight.repo} on {preflight.host}? [y/N] "
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
        print(
            f"\nerror: {resource} creation cancelled",
            file=sys.stderr,
        )
        return False
    if answer.strip().lower() in {"y", "yes"}:
        return True
    print(
        f"{resource} creation cancelled; SDD initialization is incomplete",
        file=sys.stderr,
    )
    return False


def plan_sdd_init(args: argparse.Namespace) -> InitPlan:
    """Return a read-only plan for provider work and generated files."""
    path = getattr(args, "path", None)
    project_root, management = _sdd_project_management(path)
    if not is_project_directory(project_root):
        return InitPlan(
            command="sdd",
            label="SDD",
            summary=_NON_PROJECT_SDD_MESSAGE,
            actions=(),
            blockers=(_NON_PROJECT_SDD_MESSAGE,),
        )
    if management.error is not None:
        return InitPlan(
            command="sdd",
            label="SDD",
            summary="cannot determine whether the repository is SASE-managed",
            actions=(),
            blockers=(management.error,),
        )
    if not management.is_sase_managed:
        return InitPlan(
            command="sdd",
            label="SDD",
            summary=_UNMANAGED_SDD_MESSAGE,
            actions=(),
            warnings=(_UNMANAGED_SDD_MESSAGE,),
            blockers=(),
        )

    from sase.sdd.files import plan_sdd_sidecar_init_actions, plan_sdd_init_actions
    from sase.sdd.store import resolve_sdd_dir

    policy = _project_provider_sdd_policy(project_root)
    actions: list[InitAction] = []
    if policy == "separate_repo":
        roots = _split_sidecar_roots(project_root)
        actions.extend(_plan_split_sidecar_repo_actions(project_root, roots))
        for kind, root in roots.items():
            actions.extend(
                InitAction(
                    path=action.path,
                    operation=action.operation,
                    detail=action.detail,
                    new_content=action.new_content,
                )
                for action in plan_sdd_sidecar_init_actions(kind, root)
            )
        return InitPlan(
            command="sdd",
            label="SDD",
            summary=_summarize_sdd_actions(actions),
            actions=tuple(actions),
            warnings=(),
            blockers=(),
        )
    generated_path = str(resolve_sdd_dir(project_root, 1))
    from sase.sdd._prompt_migration import plan_legacy_prompt_migration

    sdd_root = Path(generated_path)
    migration_plan = plan_legacy_prompt_migration(sdd_root)
    migration_warnings: list[str] = []
    for migration in migration_plan:
        if migration.warning:
            migration_warnings.append(migration.warning)
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
        for action in plan_sdd_init_actions(generated_path)
    )

    return InitPlan(
        command="sdd",
        label="SDD",
        summary=_summarize_sdd_actions(actions),
        actions=tuple(actions),
        warnings=tuple(migration_warnings),
        blockers=(),
    )


def _summarize_sdd_actions(actions: list[InitAction]) -> str:
    if not actions:
        return "SDD provider storage, README files, and directory map are current"

    sidecar_actions = [action for action in actions if _is_sidecar_repo_action(action)]
    generated_actions = [
        action for action in actions if not _is_sidecar_repo_action(action)
    ]
    summaries: list[str] = []
    if sidecar_actions:
        summaries.append("create or connect provider sidecar SDD repositories")
    if generated_actions:
        summaries.append(_summarize_generated_sdd_actions(generated_actions))
    if not summaries:
        return "SDD provider storage, README files, and directory map are current"
    if len(summaries) == 1:
        return summaries[0]
    return f"{', '.join(summaries[:-1])} and {summaries[-1]}"


def _sdd_project_management(
    path: str | Path | None,
) -> tuple[Path, ProjectManagementStatus]:
    from .sdd_init_config import resolve_sdd_init_config_path

    config_path = resolve_sdd_init_config_path(path)
    return config_path.parent, project_management_status(config_path)


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


def _split_sidecar_provider_setup_needed(project_root: Path) -> bool:
    from sase.sdd._paths import get_primary_workspace_dir
    from sase.sdd.store import read_sdd_store_record

    primary = Path(get_primary_workspace_dir(str(project_root), 1))
    record = read_sdd_store_record(primary)
    return record is None or not record.is_sidecar_storage


def _split_sidecar_roots(project_root: Path) -> dict[str, Path]:
    from sase.linked_repos import sidecar_repo_clone_dir

    return {
        kind: Path(sidecar_repo_clone_dir(project_root, kind))
        for kind in ("plans", "research")
    }


def _plan_split_sidecar_repo_actions(
    project_root: Path, roots: dict[str, Path]
) -> list[InitAction]:
    if not _split_sidecar_provider_setup_needed(project_root):
        return []
    return [
        InitAction(
            path=root,
            operation="create",
            detail=f"create or connect the provider {kind} sidecar repository",
        )
        for kind, root in roots.items()
    ]


def _is_sidecar_repo_action(action: InitAction) -> bool:
    detail = action.detail.casefold()
    return detail.startswith("create or connect") and "sidecar" in detail


def _summarize_generated_sdd_actions(actions: list[InitAction]) -> str:
    operations = {action.operation for action in actions}
    if operations == {"create"}:
        return "create SDD README files and directory map"
    if operations == {"update"}:
        return "update SDD README files and directory map"
    return "refresh SDD README files and directory map"


def _handle_validate(args: argparse.Namespace) -> None:
    from sase.sdd.links import validate_sdd_tree, validation_to_json

    validation = validate_sdd_tree(args.path, strict=args.strict)
    if args.json:
        print(json.dumps(validation_to_json(validation), indent=2))
    elif not args.quiet or not validation.ok:
        _print_validation(validation, show_warnings=args.show_warnings)
    sys.exit(0 if validation.ok else 1)


def _handle_links(args: argparse.Namespace) -> None:
    from sase.sdd.links import collect_sdd_links, resolve_sdd_root

    root = resolve_sdd_root(args.path)
    if not root.is_dir():
        print(f"SDD path does not exist or is not a directory: {root}", file=sys.stderr)
        sys.exit(1)
    rows = collect_sdd_links(root)
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for row in rows:
            target = row["target"] or "-"
            status = "ok" if row["bidirectional"] else "broken"
            print(f"{row['path']} -> {target} [{status}]")
    sys.exit(0)


def _handle_list(args: argparse.Namespace) -> None:
    from sase.sdd.links import files_to_json, list_sdd_files, resolve_sdd_root

    root = resolve_sdd_root(getattr(args, "path", None))
    if not root.is_dir():
        print(f"SDD path does not exist or is not a directory: {root}", file=sys.stderr)
        sys.exit(1)
    files = list_sdd_files(root, kind=args.kind)
    if args.json:
        print(json.dumps(files_to_json(files), indent=2))
    else:
        for file in files:
            print(f"{file.kind}\t{file.relpath}")
    sys.exit(0)


def _handle_path(args: argparse.Namespace) -> None:
    from sase.sdd.store import (
        ensure_sdd_kind_clone,
        resolve_sdd_dir,
        resolve_sdd_kind_dir,
    )

    workspace_dir = Path.cwd()
    workspace_num = _current_workspace_num()
    kind = getattr(args, "kind", None)
    resolved_kind = kind or "plans"
    if getattr(args, "ensure", False):
        ensure_sdd_kind_clone(workspace_dir, workspace_num, resolved_kind, strict=True)
    root = resolve_sdd_dir(workspace_dir, workspace_num)
    print(
        root
        if kind is None
        else resolve_sdd_kind_dir(workspace_dir, workspace_num, kind)
    )
    sys.exit(0)


def _current_workspace_num() -> int:
    try:
        from .utils import ensure_project_file_and_get_workspace_num

        _, workspace_num, _ = ensure_project_file_and_get_workspace_num(
            create_missing=False
        )
    except Exception:
        workspace_num = None
    return workspace_num or 1


def _handle_repair_links(args: argparse.Namespace) -> None:
    from sase.sdd.links import repair_sdd_links, repair_to_json

    if args.write and getattr(args, "path", None) is None:
        from sase.sdd.store import materialize_sdd_store

        materialize_sdd_store(Path.cwd(), _current_workspace_num())
    report = repair_sdd_links(args.path, write=args.write)
    print(json.dumps(repair_to_json(report), indent=2))
    has_errors = any(issue.severity == "error" for issue in report.issues)
    sys.exit(1 if has_errors else 0)


def _print_validation(validation: Any, *, show_warnings: bool) -> None:
    warning_count = len(validation.warnings)
    hint = (
        " (use --show-warnings to display)"
        if warning_count and not show_warnings
        else ""
    )
    if validation.ok:
        print(
            f"SDD validation passed: {len(validation.files)} files, "
            f"{warning_count} warnings{hint}"
        )
    else:
        print(
            f"SDD validation failed: {len(validation.errors)} errors, "
            f"{warning_count} warnings{hint}"
        )
    for issue in validation.issues:
        if issue.severity == "warning" and not show_warnings:
            continue
        stream = sys.stderr if issue.severity == "error" else sys.stdout
        print(
            f"{issue.severity}: {issue.path}: {issue.message} ({issue.code})",
            file=stream,
        )
