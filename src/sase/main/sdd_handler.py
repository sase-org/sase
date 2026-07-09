"""Handler for ``sase sdd`` subcommands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any
from urllib.parse import urlparse

from rich.console import Console

from .init_plan import InitAction, InitPlan
from .init_project_scope import is_project_directory

_NON_PROJECT_SDD_MESSAGE = (
    "sase init sdd: not a project directory (no VCS found); skipping SDD initialization"
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
    sys.exit(_run_sdd_migrate(args))


def _run_sdd_migrate(args: argparse.Namespace) -> int:
    """Migrate SDD files to a companion repository and return an exit code."""
    from sase.sdd.migrate import SddMigrationError, migrate_sdd_to_separate_repo

    path = getattr(args, "path", None)
    project_root = _sdd_init_project_root(path)
    if not is_project_directory(project_root):
        print(
            "sase sdd migrate: not a project directory (no VCS found)", file=sys.stderr
        )
        return 1

    try:
        result = migrate_sdd_to_separate_repo(
            project_root,
            workspace_num=1,
            create=bool(getattr(args, "create", False)),
            remove_in_tree=bool(getattr(args, "remove_in_tree", False)),
        )
    except SddMigrationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"SDD migrated to {result.record.repo or 'companion repository'}")
    print(f"SDD root: {result.sdd_dir}")
    print(f"Config: {result.config_path}")
    if result.committed:
        print("Committed SDD changes in companion repo")
    if result.pushed:
        print("Pushed companion repo")
    if result.removed_in_tree:
        print("Removed tracked in-tree sdd/ files in a separate commit")
    return 0


def run_sdd_init(args: argparse.Namespace) -> int:
    """Enable project-local SDD config, refresh generated files, and return code."""
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

    from sase.sdd.files import ensure_sdd_initialized, expected_sdd_readme
    from .sdd_init_config import SddInitConfigError, write_sdd_init_config

    path = getattr(args, "path", None)
    storage = getattr(args, "storage", None)
    if not is_project_directory(_sdd_init_project_root(path)):
        print(_NON_PROJECT_SDD_MESSAGE, file=sys.stderr)
        return 1

    project_root = _sdd_init_project_root(path)
    effective_storage = _effective_init_storage(project_root, storage)
    try:
        from sase.sdd.store import SddMaterializationError, materialize_sdd_store

        if effective_storage == "separate_repo":
            return _run_separate_repo_sdd_init(path, project_root)
        if storage == "auto":
            write_sdd_init_config(path, storage=storage)
            _delete_negative_sdd_record(project_root)
            materialize_sdd_store(project_root, 1)
        elif storage in {"in_tree", "local"}:
            write_sdd_init_config(path, storage=storage)
        elif effective_storage in {"auto", "local"}:
            _delete_negative_sdd_record(project_root)
            materialize_sdd_store(project_root, 1)
            write_sdd_init_config(path)
        else:
            write_sdd_init_config(path)
    except SddMaterializationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except SddInitConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    generated_path = _sdd_init_generated_path(path, project_root, storage)
    ensure_sdd_initialized(generated_path)
    readme_path = expected_sdd_readme(generated_path).path
    print(readme_path)
    return 0


def _run_separate_repo_sdd_init(path: str | Path | None, project_root: Path) -> int:
    from sase.sdd.files import ensure_sdd_initialized, expected_sdd_readme
    from sase.sdd._paths import get_primary_workspace_dir
    from sase.sdd.store import (
        SddMaterializationError,
        create_and_materialize_sdd_store,
        read_sdd_store_record,
    )
    from .sdd_init_config import SddInitConfigError, plan_sdd_init_config
    from .sdd_init_config import write_sdd_init_config

    config_plan = plan_sdd_init_config(path, storage="separate_repo")
    if config_plan.blockers:
        raise SddInitConfigError("\n".join(config_plan.blockers))

    console = _sdd_init_console()
    project_label, host = _sdd_init_remote_context(project_root)
    console.print(f"Setting up separate-repo SDD storage for {project_label}")
    console.print(f"  -> ensuring companion repository on {host} ...")

    if _should_migrate_in_tree_sdd_on_init(project_root):
        from sase.sdd.migrate import SddMigrationError, migrate_sdd_to_separate_repo

        console.print("  -> migrating existing in-tree SDD artifacts ...")
        try:
            result = migrate_sdd_to_separate_repo(
                project_root,
                workspace_num=1,
                create=True,
                remove_in_tree=False,
            )
        except SddMigrationError as exc:
            console.print(f"error: {exc}", style="red")
            return 1

        repo = result.record.repo or "companion repository"
        console.print(f"  ok migrated SDD artifacts to {repo}")
        console.print(
            f"  ok materialized SDD store at "
            f"{_display_sdd_init_path(result.sdd_dir, project_root)}"
        )
        console.print("  ok initialized guides + beads")
        console.print(f"SDD ready: separate repository {repo}")
        print(expected_sdd_readme(str(result.sdd_dir)).path)
        return 0

    try:
        _delete_negative_sdd_record(project_root)
        outcome = create_and_materialize_sdd_store(project_root, 1)
    except SddMaterializationError as exc:
        console.print(f"error: {exc}", style="red")
        return 1

    primary = Path(get_primary_workspace_dir(str(project_root), 1))
    record = read_sdd_store_record(primary)
    repo = (record.repo if record else outcome.repo) or "companion repository"
    action = "created" if outcome.created else "using existing"
    console.print(f"  ok {action} {repo}")
    console.print(
        f"  ok materialized SDD store at "
        f"{_display_sdd_init_path(outcome.store.sdd_dir, project_root)}"
    )

    write_sdd_init_config(path, storage="separate_repo")
    generated_path = _sdd_init_generated_path(path, project_root, "separate_repo")
    ensure_sdd_initialized(generated_path)
    readme_path = expected_sdd_readme(generated_path).path
    console.print("  ok initialized guides + beads")
    console.print(f"SDD ready: separate repository {repo}")
    print(readme_path)
    return 0


def plan_sdd_init(args: argparse.Namespace) -> InitPlan:
    """Return a read-only plan for SDD config and generated files."""
    from sase.sdd.files import plan_sdd_init_actions
    from .sdd_init_config import plan_sdd_init_config

    path = getattr(args, "path", None)
    project_root = _sdd_init_project_root(path)
    if not is_project_directory(project_root):
        return InitPlan(
            command="sdd",
            label="SDD",
            summary=_NON_PROJECT_SDD_MESSAGE,
            actions=(),
            blockers=(_NON_PROJECT_SDD_MESSAGE,),
        )

    storage_arg = getattr(args, "storage", None)
    effective_storage = _effective_init_storage(project_root, storage_arg)
    config_storage = (
        "separate_repo" if effective_storage == "separate_repo" else storage_arg
    )
    config_plan = plan_sdd_init_config(path, storage=config_storage)
    actions = []
    if config_plan.action is not None:
        actions.append(config_plan.action)
    if effective_storage == "separate_repo":
        companion_action = _plan_sdd_companion_repo_action(project_root)
        if companion_action is not None:
            actions.append(companion_action)
        migration_action = _plan_in_tree_sdd_migration_action(project_root)
        if migration_action is not None:
            actions.append(migration_action)
    generated_path = _sdd_init_generated_path(
        path,
        project_root,
        storage_arg,
    )
    actions.extend(
        InitAction(
            path=action.path,
            operation=action.operation,
            detail=action.detail,
        )
        for action in plan_sdd_init_actions(generated_path)
    )

    return InitPlan(
        command="sdd",
        label="SDD",
        summary=_summarize_sdd_actions(actions),
        actions=tuple(actions),
        blockers=config_plan.blockers,
    )


def _summarize_sdd_actions(actions: list[InitAction]) -> str:
    if not actions:
        return "SDD config, README files, and directory map are current"

    config_actions = [action for action in actions if action.path.name == "sase.yml"]
    companion_actions = [
        action for action in actions if _is_companion_repo_action(action)
    ]
    migration_actions = [
        action for action in actions if _is_in_tree_sdd_migration_action(action)
    ]
    generated_actions = [
        action
        for action in actions
        if action.path.name != "sase.yml"
        and not _is_companion_repo_action(action)
        and not _is_in_tree_sdd_migration_action(action)
    ]
    summaries: list[str] = []
    if config_actions:
        summaries.append(_summarize_sdd_config_action(config_actions[0]))
    if companion_actions:
        summaries.append("create or connect GitHub companion SDD repository")
    if migration_actions:
        summaries.append("migrate existing in-tree SDD artifacts")
    if generated_actions:
        summaries.append(_summarize_generated_sdd_actions(generated_actions))
    if not summaries:
        return "SDD config, README files, and directory map are current"
    if len(summaries) == 1:
        return summaries[0]
    return f"{', '.join(summaries[:-1])} and {summaries[-1]}"


def _summarize_sdd_config_action(action: InitAction) -> str:
    if action.detail == "enable sdd.version_controlled":
        return "write legacy SDD init config"
    return action.detail


def _sdd_init_project_root(path: str | Path | None) -> Path:
    from .sdd_init_config import resolve_sdd_init_config_path

    return resolve_sdd_init_config_path(path).parent


def _sdd_init_generated_path(
    path: str | Path | None, project_root: Path, storage: str | None
) -> str | None:
    effective_storage = _effective_init_storage(project_root, storage)
    if effective_storage in {"auto", "local", "separate_repo"}:
        return str(project_root / ".sase" / "sdd")
    return str(path) if path is not None else None


def _effective_init_storage(project_root: Path, storage_arg: str | None) -> str | None:
    if storage_arg is not None and storage_arg != "auto":
        return storage_arg

    configured_storage = _configured_project_sdd_storage(project_root)
    if configured_storage is not None and configured_storage != "auto":
        return configured_storage

    provider_policy = _project_provider_sdd_policy(project_root)
    if provider_policy is not None:
        return provider_policy
    if storage_arg == "auto" or configured_storage == "auto":
        return "auto"
    return None


def _configured_project_sdd_storage(project_root: Path) -> str | None:
    config_path = project_root / "sase.yml"
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError:
        return None

    try:
        import yaml  # type: ignore[import-untyped]

        data = yaml.safe_load(text)
    except Exception:
        return None

    if not isinstance(data, dict):
        return None
    sdd_config = data.get("sdd")
    if not isinstance(sdd_config, dict):
        return None
    storage = sdd_config.get("storage")
    if storage in {"auto", "in_tree", "local", "separate_repo"}:
        return str(storage)
    return None


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


def _plan_sdd_companion_repo_action(project_root: Path) -> InitAction | None:
    from sase.sdd._paths import get_primary_workspace_dir
    from sase.sdd.store import read_sdd_store_record

    primary = Path(get_primary_workspace_dir(str(project_root), 1))
    record = read_sdd_store_record(primary)
    if record is not None and record.discovery != "not_found":
        return None
    return InitAction(
        path=project_root / ".sase" / "sdd",
        operation="create",
        detail="create or connect the GitHub companion SDD repository",
    )


def _plan_in_tree_sdd_migration_action(project_root: Path) -> InitAction | None:
    if not _should_migrate_in_tree_sdd_on_init(project_root):
        return None
    return InitAction(
        path=project_root / ".sase" / "sdd",
        operation="update",
        detail="migrate existing in-tree SDD artifacts into companion repository",
    )


def _is_companion_repo_action(action: InitAction) -> bool:
    detail = action.detail.casefold()
    return detail.startswith("create or connect") and "companion" in detail


def _is_in_tree_sdd_migration_action(action: InitAction) -> bool:
    return "migrate existing in-tree sdd artifacts" in action.detail.casefold()


def _has_existing_in_tree_sdd_artifacts(project_root: Path) -> bool:
    source = project_root / "sdd"
    if not source.is_dir():
        return False
    try:
        return any(item.name != ".git" for item in source.iterdir())
    except OSError:
        return False


def _should_migrate_in_tree_sdd_on_init(project_root: Path) -> bool:
    if _configured_project_sdd_storage(project_root) == "separate_repo":
        return False
    return _has_existing_in_tree_sdd_artifacts(project_root)


def _delete_negative_sdd_record(project_root: Path) -> None:
    from sase.sdd._paths import get_primary_workspace_dir
    from sase.sdd.store import delete_sdd_store_record, read_sdd_store_record

    primary = Path(get_primary_workspace_dir(str(project_root), 1))
    record = read_sdd_store_record(primary)
    if record is not None and record.discovery == "not_found":
        delete_sdd_store_record(primary)


def _sdd_init_console() -> Console:
    is_tty = sys.stderr.isatty()
    return Console(
        file=sys.stderr,
        force_terminal=is_tty,
        color_system="auto" if is_tty else None,
        no_color=not is_tty,
        soft_wrap=True,
    )


def _sdd_init_remote_context(project_root: Path) -> tuple[str, str]:
    origin = _read_project_origin(project_root)
    parsed = _parse_remote_origin(origin)
    if parsed is None:
        return project_root.name, "the provider"
    host, owner, repo = parsed
    return f"{owner}/{repo}", host


def _read_project_origin(project_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _parse_remote_origin(value: str | None) -> tuple[str, str, str] | None:
    if not value:
        return None
    raw = value.strip()
    if "://" not in raw:
        match = re.match(r"^(?:[^@/]+@)?(?P<host>[^:/]+):(?P<path>.+)$", raw)
        if not match:
            return None
        host = match.group("host").strip().lower().rstrip("/")
        path = match.group("path")
    else:
        parsed = urlparse(raw)
        host = parsed.netloc.rsplit("@", 1)[-1].strip().lower().rstrip("/")
        path = parsed.path.lstrip("/")

    parts = [part for part in path.strip("/").split("/") if part]
    if len(parts) != 2:
        return None
    owner = parts[0].strip()
    repo = parts[1].removesuffix(".git").strip()
    if not host or not owner or not repo:
        return None
    return host, owner, repo


def _display_sdd_init_path(path: Path, project_root: Path) -> str:
    try:
        return str(path.resolve(strict=False).relative_to(project_root.resolve()))
    except ValueError:
        return str(path)


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
    from sase.sdd.store import resolve_sdd_dir

    workspace_dir = Path.cwd()
    workspace_num = _current_workspace_num()
    root = resolve_sdd_dir(workspace_dir, workspace_num)
    kind = getattr(args, "kind", None)
    print(root if kind is None else root / kind)
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
