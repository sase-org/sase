"""Handler for the 'sase memory' command."""

import argparse
import sys


def handle_memory_command(args: argparse.Namespace) -> None:
    """Handle the 'sase memory' subcommands."""
    memory_sub = getattr(args, "memory_subcommand", None)

    if memory_sub == "init":
        _handle_init()

    elif memory_sub == "add":
        _handle_add(args)

    elif memory_sub == "show":
        _handle_show(args)

    elif memory_sub == "list":
        _handle_list(args)

    elif memory_sub == "inject":
        _handle_inject(args)

    elif memory_sub == "rm":
        _handle_rm(args)

    elif memory_sub == "tree":
        _handle_tree(args)

    else:
        print("Usage: sase memory {init,add,show,list,rm,inject,tree}")
        sys.exit(1)


def _handle_inject(args: argparse.Namespace) -> None:
    from sase.memory.inject import build_injection
    from sase.memory.repo import repo_exists

    if not repo_exists():
        print("Memory repo not initialized. Run: sase memory init", file=sys.stderr)
        sys.exit(1)

    project = _resolve_project(args)

    max_tokens: int | None = None
    try:
        from sase.config import load_merged_config

        cfg = load_merged_config()
        mem_cfg = cfg.get("memory", {})
        if isinstance(mem_cfg, dict):
            max_tokens = mem_cfg.get("max_system_tokens")
    except Exception:
        pass

    output = build_injection(project, max_system_tokens=max_tokens)
    if output:
        print(output)
    sys.exit(0)


def _handle_init() -> None:
    from sase.memory.repo import ensure_repo, repo_exists

    already = repo_exists()
    path = ensure_repo()
    if already:
        print(f"Memory repo already initialized at {path}")
    else:
        print(f"Initialized memory repo at {path}")
    sys.exit(0)


def _handle_add(args: argparse.Namespace) -> None:
    from sase.memory.models import MemoryType
    from sase.memory.repo import repo_exists
    from sase.memory.store import add

    if not repo_exists():
        print("Memory repo not initialized. Run: sase memory init", file=sys.stderr)
        sys.exit(1)

    project = _resolve_project(args)
    memory_type = MemoryType(args.memory_type)

    if args.message:
        body = args.message
    else:
        body = sys.stdin.read().strip()
        if not body:
            print(
                "No content provided. Use -m or pipe content via stdin.",
                file=sys.stderr,
            )
            sys.exit(1)

    try:
        filepath = add(
            name=args.name,
            description=args.description,
            memory_type=memory_type,
            body=body,
            project=project,
            system=args.system,
        )
    except FileExistsError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    from sase.memory.repo import get_repo_path

    print(f"Created: {filepath.relative_to(get_repo_path())}")
    sys.exit(0)


def _handle_show(args: argparse.Namespace) -> None:
    from sase.memory.repo import repo_exists
    from sase.memory.store import show

    if not repo_exists():
        print("Memory repo not initialized. Run: sase memory init", file=sys.stderr)
        sys.exit(1)

    project = _resolve_project(args)

    try:
        mem = show(args.name, project=project)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    print(mem.to_markdown(), end="")
    sys.exit(0)


def _handle_list(args: argparse.Namespace) -> None:
    from sase.memory.repo import repo_exists
    from sase.memory.store import list_memories

    if not repo_exists():
        print("Memory repo not initialized. Run: sase memory init", file=sys.stderr)
        sys.exit(1)

    project = getattr(args, "project", None)
    memories = list_memories(project=project)

    if not memories:
        scope = f"project '{project}'" if project else "all"
        print(f"No memories found ({scope})")
        sys.exit(0)

    for rel_path, mem in memories:
        sys_marker = " [system]" if "/system/" in rel_path else ""
        print(f"  {rel_path}{sys_marker}")
        print(f"    {mem.memory_type.value}: {mem.description}")
    sys.exit(0)


def _handle_rm(args: argparse.Namespace) -> None:
    from sase.memory.repo import get_repo_path, repo_exists
    from sase.memory.store import rm

    if not repo_exists():
        print("Memory repo not initialized. Run: sase memory init", file=sys.stderr)
        sys.exit(1)

    project = _resolve_project(args)

    try:
        filepath = rm(args.name, project=project)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    print(f"Removed: {filepath.relative_to(get_repo_path())}")
    sys.exit(0)


def _handle_tree(args: argparse.Namespace) -> None:
    from sase.memory.repo import get_filetree, repo_exists

    if not repo_exists():
        print("Memory repo not initialized. Run: sase memory init", file=sys.stderr)
        sys.exit(1)

    project = getattr(args, "project", None)
    tree = get_filetree(project=project)
    if tree:
        print(tree)
    else:
        print("(empty)")
    sys.exit(0)


def _resolve_project(args: argparse.Namespace) -> str | None:
    """Resolve the project name from args or auto-detect from CWD."""
    project = getattr(args, "project", None)
    if project:
        return project

    from sase.bead.project_name import infer_project_name_from_cwd

    return infer_project_name_from_cwd()
