"""Sidecar planning, initialization, and confirmation for ``sase repo init``."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import TYPE_CHECKING, TextIO

from sase._linked_repo_config import (
    AGENTS_SIDECAR_ROLE,
    ATTACHMENTS_PRIVATE_SIDECAR_ROLE,
    ATTACHMENTS_SIDECAR_ROLE,
)
from sase.sdd._sidecar_bare import is_bare_sidecar_clone

from .init_plan import InitAction

if TYPE_CHECKING:
    from sase.sdd._sidecar_init import SidecarInitSpec
    from sase.workspace_provider import SddSidecarPreflight


#: Hidden sidecar roles whose absence never blocks ``sase repo init``: a
#: declined or missing role simply continues init without that sidecar.
_OPTIONAL_HIDDEN_SIDECAR_ROLES = frozenset(
    {
        AGENTS_SIDECAR_ROLE,
        ATTACHMENTS_SIDECAR_ROLE,
        ATTACHMENTS_PRIVATE_SIDECAR_ROLE,
    }
)


def run_configured_sidecars(
    args: argparse.Namespace,
    project_root: Path,
    specs: tuple[SidecarInitSpec, ...],
) -> int:
    """Create or connect provider-managed sidecars and initialize their files."""

    from sase.sdd._sidecar_init import initialize_sidecars, preflight_sidecars
    from sase.sdd.store import SddMaterializationError

    authorizations: dict[str, bool] = {}
    preflights = preflight_sidecars(project_root, 1, specs)
    for preflight in preflights.values():
        if preflight.status == "unavailable":
            detail = preflight.message or (
                f"could not verify {preflight.provider} sidecar repository {preflight.repo}"
            )
            raise SddMaterializationError(detail)
        if preflight.status not in {"found", "not_found"}:
            raise SddMaterializationError(
                "The workspace provider returned an invalid sidecar preflight "
                "result. Update the provider plugin and rerun `sase repo init`."
            )

    selected_roles = {spec.role for spec in specs}
    missing = {
        role: preflight
        for role, preflight in preflights.items()
        if preflight.status == "not_found"
    }
    stdin: TextIO = getattr(args, "_init_stdin", None) or sys.stdin
    if missing and getattr(args, "onboarding", False) and not stdin.isatty():
        deferred_document_roles = False
        for role, preflight in missing.items():
            print(
                f"warning: {preflight.provider} sidecar repository "
                f"{preflight.repo} is missing; run `sase repo init` "
                "interactively to create it",
                file=sys.stderr,
            )
            if role in _OPTIONAL_HIDDEN_SIDECAR_ROLES:
                selected_roles.discard(role)
            else:
                deferred_document_roles = True
        if deferred_document_roles:
            return 0

    for role, preflight in preflights.items():
        if preflight.status == "not_found":
            if role not in selected_roles:
                continue
            if not _confirm_sidecar_creation(args, role, preflight):
                if role in _OPTIONAL_HIDDEN_SIDECAR_ROLES:
                    selected_roles.discard(role)
                    continue
                return 1
            authorizations[role] = True

    selected_specs = tuple(spec for spec in specs if spec.role in selected_roles)
    if not selected_specs:
        return 0

    outcome = initialize_sidecars(
        project_root,
        1,
        selected_specs,
        creation_authorized=authorizations,
        publish_sidecar_changes=not getattr(args, "no_commit", False),
    )
    for spec in selected_specs:
        print(_initialized_sidecar_path(outcome.roots[spec.role], spec.role))
    return 0


def run_materialized_sidecars(
    project_root: Path,
    specs: tuple[SidecarInitSpec, ...],
    recorded_roles: frozenset[str],
    *,
    publish_sidecar_changes: bool = True,
) -> int:
    """Initialize sidecars already materialized in the compatibility layout."""

    from sase.sdd._sidecar_init import (
        initialize_materialized_sidecars,
        sidecar_clone_root,
    )
    from sase.sdd.store import SddMaterializationError

    materialized: list[SidecarInitSpec] = []
    for spec in specs:
        root = sidecar_clone_root(project_root, spec.role)
        if (root / ".git").is_dir() or is_bare_sidecar_clone(root):
            materialized.append(spec)
        elif spec.role not in recorded_roles:
            raise SddMaterializationError(
                f"configured {spec.role} sidecar is not materialized at {root}; "
                "rerun `sase repo init` with the repository's workspace provider"
            )
    roots = initialize_materialized_sidecars(
        project_root,
        materialized,
        publish_sidecar_changes=publish_sidecar_changes,
    )
    for spec in materialized:
        print(_initialized_sidecar_path(roots[spec.role], spec.role))
    return 0


def _initialized_sidecar_path(root: Path, role: str) -> Path:
    """Return the init echo path for one sidecar root.

    The attachment stores are bare object stores with no README, so init
    prints the bare clone path itself.
    """

    if role in {ATTACHMENTS_SIDECAR_ROLE, ATTACHMENTS_PRIVATE_SIDECAR_ROLE}:
        return root
    return root / "README.md"


def _confirm_sidecar_creation(
    args: argparse.Namespace,
    role: str,
    preflight: SddSidecarPreflight,
) -> bool:
    if role == AGENTS_SIDECAR_ROLE:
        return _confirm_agents_sidecar_creation(args, preflight)
    if role == ATTACHMENTS_SIDECAR_ROLE:
        return _confirm_attachments_sidecar_creation(args, preflight)
    if role == ATTACHMENTS_PRIVATE_SIDECAR_ROLE:
        return _confirm_attachments_private_sidecar_creation(args, preflight)

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


def _confirm_agents_sidecar_creation(
    args: argparse.Namespace,
    preflight: SddSidecarPreflight,
) -> bool:
    stdin: TextIO = getattr(args, "_init_stdin", None) or sys.stdin
    resource = f"{preflight.provider} agents sidecar repository"
    if not stdin.isatty():
        print(
            f"warning: {resource} creation refused: interactive y/yes "
            "confirmation is required; run `sase repo init` interactively "
            "to create it; continuing without the agents sidecar",
            file=sys.stderr,
        )
        return False

    input_func = getattr(args, "_init_input_func", None) or input
    visibility = preflight.visibility.strip() or "public"
    prompt = (
        "The agents sidecar will PUBLISH SASE agent data for this project "
        "across machines. One publication includes the committing agent's "
        "complete project-scoped top-level hood: active prompts, waiting, "
        "failed, terminal, and dismissed runs, allowlisted metadata, commit "
        "associations, and readable chat transcripts. Later syncs can refresh "
        "the same runs with newly available transcripts.\n"
        f"Repository visibility: {visibility.upper()}.\n"
        "Set repos.sidecar.builtin.agents.visibility: private in sase/sase.yml "
        "for a private repository, or disabled: true to opt out.\n\n"
        f"Create {visibility} {preflight.provider} agents sidecar repository "
        f"{preflight.repo} on {preflight.host}? [y/N] "
    )
    try:
        answer = input_func(prompt)
    except EOFError:
        print(
            f"warning: {resource} creation refused: no confirmation was "
            "received; rerun `sase repo init` interactively to create it; "
            "continuing without the agents sidecar",
            file=sys.stderr,
        )
        return False
    except KeyboardInterrupt:
        print(
            f"\nwarning: {resource} creation refused; rerun `sase repo init` "
            "interactively to create it; continuing without the agents sidecar",
            file=sys.stderr,
        )
        return False
    if answer.strip().lower() in {"y", "yes"}:
        return True
    print(
        f"warning: {resource} creation declined; continuing without the agents sidecar",
        file=sys.stderr,
    )
    return False


def _beads_remote_for_public_probe() -> str | None:
    """Return the beads sidecar remote URL for the public-store probe."""

    try:
        from pathlib import Path as _Path

        from sase._linked_repo_config import (
            merged_sidecar_entries_from_config,
            resolution_config,
        )
        from sase._linked_repo_config_keys import (
            SIDECAR_REMOTE_URL_KEY,
            SIDECAR_ROLE_KEY,
        )

        workspace = str(_Path.cwd())
        config = resolution_config(workspace, None)
        for entry in merged_sidecar_entries_from_config(
            config, primary_workspace_dir=workspace
        ):
            role = entry.get(SIDECAR_ROLE_KEY) or entry.get("role")
            if role == "beads":
                remote = entry.get(SIDECAR_REMOTE_URL_KEY) or entry.get("remote_url")
                if isinstance(remote, str) and remote.strip():
                    return remote.strip()
                raw_remote = entry.get("remote_url")
                if isinstance(raw_remote, str) and raw_remote.strip():
                    return raw_remote.strip()
                return None
    except Exception:
        return None
    return None


def _confirm_attachments_sidecar_creation(
    args: argparse.Namespace,
    preflight: SddSidecarPreflight,
) -> bool:
    stdin: TextIO = getattr(args, "_init_stdin", None) or sys.stdin
    resource = f"{preflight.provider} attachments sidecar repository"
    if not stdin.isatty():
        print(
            f"warning: {resource} creation refused: interactive confirmation "
            "is required; run `sase repo init` interactively to create it; "
            "continuing without the attachments sidecar",
            file=sys.stderr,
        )
        return False
    try:
        from sase.bead.attachments.remote_visibility import (
            resolve_remote_visibility,
        )

        beads_remote = _beads_remote_for_public_probe()
        visibility = (
            resolve_remote_visibility(beads_remote) if beads_remote else "unknown"
        )
    except Exception:
        visibility = "unknown"
    if visibility != "public":
        print(
            "warning: attachments sidecar creation refused: the beads sidecar "
            "is not public (repos.sidecar.builtin.beads.visibility: private); "
            "continuing without the attachments sidecar",
            file=sys.stderr,
        )
        return False
    input_func = getattr(args, "_init_input_func", None) or input
    prompt = (
        "The attachments sidecar will hold public bead attachment bytes for "
        "this project. Anyone who can read the beads sidecar can read it.\n"
        "Repository visibility: PUBLIC.\n"
        "Set repos.sidecar.builtin.attachments.disabled: true in sase/sase.yml "
        "to opt out.\n\n"
        f"Create public {preflight.provider} attachments sidecar repository "
        f"{preflight.repo} on {preflight.host}? [Y/n] "
    )
    try:
        answer = input_func(prompt)
    except EOFError:
        print(
            f"warning: {resource} creation refused: no confirmation was "
            "received; rerun `sase repo init` interactively to create it; "
            "continuing without the attachments sidecar",
            file=sys.stderr,
        )
        return False
    except KeyboardInterrupt:
        print(
            f"\nwarning: {resource} creation refused; rerun `sase repo init` "
            "interactively to create it; continuing without the attachments "
            "sidecar",
            file=sys.stderr,
        )
        return False
    if answer.strip() == "" or answer.strip().lower() in {"y", "yes"}:
        return True
    print(
        "warning: attachments sidecar creation declined; continuing without "
        "the attachments sidecar",
        file=sys.stderr,
    )
    return False


def _confirm_attachments_private_sidecar_creation(
    args: argparse.Namespace,
    preflight: SddSidecarPreflight,
) -> bool:
    stdin: TextIO = getattr(args, "_init_stdin", None) or sys.stdin
    resource = f"{preflight.provider} attachments-private sidecar repository"
    if not stdin.isatty():
        print(
            f"warning: {resource} creation refused: interactive y/yes "
            "confirmation is required; run `sase repo init` interactively "
            "to create it; continuing without the attachments-private sidecar",
            file=sys.stderr,
        )
        return False

    input_func = getattr(args, "_init_input_func", None) or input
    visibility = preflight.visibility.strip() or "private"
    prompt = (
        "The attachments-private sidecar will hold private bead attachment "
        "bytes for this project.\n"
        f"Repository visibility: {visibility.upper()}.\n"
        "Set repos.sidecar.builtin.attachments-private.disabled: true in "
        "sase/sase.yml to opt out.\n\n"
        f"Create {visibility} {preflight.provider} attachments-private "
        f"sidecar repository {preflight.repo} on {preflight.host}? [y/N] "
    )
    try:
        answer = input_func(prompt)
    except EOFError:
        print(
            f"warning: {resource} creation refused: no confirmation was "
            "received; rerun `sase repo init` interactively to create it; "
            "continuing without the attachments-private sidecar",
            file=sys.stderr,
        )
        return False
    except KeyboardInterrupt:
        print(
            f"\nwarning: {resource} creation refused; rerun `sase repo init` "
            "interactively to create it; continuing without the "
            "attachments-private sidecar",
            file=sys.stderr,
        )
        return False
    if answer.strip().lower() in {"y", "yes"}:
        return True
    print(
        f"warning: {resource} creation declined; continuing without the "
        "attachments-private sidecar",
        file=sys.stderr,
    )
    return False


def run_legacy_store_init(project_root: Path) -> int:
    """Initialize the legacy local or in-tree SDD store."""

    from sase.sdd.files import ensure_sdd_initialized, expected_sdd_readme
    from sase.sdd.store import materialize_sdd_store

    store = materialize_sdd_store(
        project_root,
        1,
        sdd_creation_authorized=False,
    )
    ensure_sdd_initialized(store.sdd_dir)
    print(expected_sdd_readme(str(store.sdd_dir)).path)
    return 0


def plan_legacy_store_actions(
    project_root: Path,
) -> tuple[list[InitAction], list[str]]:
    """Plan file initialization for the legacy SDD store."""

    from sase.sdd.files import plan_sdd_init_actions
    from sase.sdd.store import resolve_sdd_dir

    sdd_root = Path(resolve_sdd_dir(project_root, 1))
    actions = [
        InitAction(
            path=action.path,
            operation=action.operation,
            detail=action.detail,
            new_content=action.new_content,
        )
        for action in plan_sdd_init_actions(str(sdd_root))
    ]
    return actions, []


def plan_sidecar_actions(
    project_root: Path,
    specs: tuple[SidecarInitSpec, ...],
    recorded_roles: frozenset[str],
) -> tuple[list[InitAction], list[str], bool]:
    """Plan provider connection and guide-file actions for sidecars."""

    from sase.sdd._sidecar_init import (
        resolve_sidecar_clone_root,
        unresolved_project_key_message,
    )
    from sase.sdd.files import plan_sdd_sidecar_init_actions

    actions: list[InitAction] = []
    warnings: list[str] = []
    requires_tty = False
    roots: dict[str, Path] = {}
    for spec in specs:
        root = resolve_sidecar_clone_root(project_root, spec.role)
        if root is None:
            warnings.append(
                f"skipped {spec.role} sidecar planning: "
                f"{unresolved_project_key_message(project_root, role=spec.role)}"
            )
            continue
        roots[spec.role] = root
        clone_exists = (root / ".git").is_dir() or is_bare_sidecar_clone(root)
        needs_connection = not clone_exists and spec.role not in recorded_roles
        if needs_connection and spec.role == ATTACHMENTS_PRIVATE_SIDECAR_ROLE:
            warnings.append(
                "optional private attachment store attachments-private is not set up; "
                "attachments stay local-only — run `sase repo init` to create it"
            )
            continue
        if needs_connection:
            requires_tty = True
            detail = f"create or connect the provider {spec.role} sidecar repository"
            if spec.role in (
                AGENTS_SIDECAR_ROLE,
                ATTACHMENTS_SIDECAR_ROLE,
                ATTACHMENTS_PRIVATE_SIDECAR_ROLE,
            ):
                detail += (
                    f" with configured {spec.visibility} visibility at the "
                    "machine-level hidden path"
                )
            actions.append(
                InitAction(
                    path=root,
                    operation="create",
                    detail=detail,
                )
            )
        if spec.role in {ATTACHMENTS_SIDECAR_ROLE, ATTACHMENTS_PRIVATE_SIDECAR_ROLE}:
            # The bare object stores have no guide files to plan.
            continue
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
    plans_root = roots.get("plans")
    beads_root = roots.get("beads")
    if (
        plans_root is not None
        and beads_root is not None
        and "beads" not in recorded_roles
        and (plans_root / "beads").is_dir()
    ):
        actions.append(
            InitAction(
                path=beads_root,
                operation="update",
                detail="adopt bead state from the plans sidecar",
            )
        )
    return actions, warnings, requires_tty


__all__ = [
    "plan_legacy_store_actions",
    "plan_sidecar_actions",
    "run_configured_sidecars",
    "run_legacy_store_init",
    "run_materialized_sidecars",
]
