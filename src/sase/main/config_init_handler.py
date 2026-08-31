"""Interactive owner-identity initialization for SASE configuration."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import re
import socket
import sys
from pathlib import Path
from typing import TextIO

from sase.config import core as config_core
from sase.config._edit_types import ConfigEditError
from sase.config._edit_yaml import set_key, unset_key
from sase.config.targets import overlay_config_path, resolve_write_path
from sase.core.agent_identity_facade import validate_agent_username
from sase.core.paths import machine_name_path

from ._init_chezmoi_deploy import (
    ChezmoiDeployBehavior,
    defer_chezmoi_paths,
    deploy_to_chezmoi,
)
from ._init_chezmoi_ignore import (
    chezmoi_hostname,
    chezmoi_target_entry,
    ensure_machine_ignore_entry,
)
from .init_plan import InitAction, InitOperation, InitPlan

_COMMAND_LABEL = "config init"
_USERNAME_CONTRACT = (
    "Your SASE username must be globally unique, should be reused on every "
    "machine you own, and should normally be your GitHub username."
)


def _existing_machine_names() -> tuple[str, ...]:
    """Return valid identities declared by any raw user overlay."""
    return config_core.discover_machine_names()


def _selected_overlay_missing_username(
    snapshot: config_core.AgentOwnerConfigSnapshot,
) -> bool:
    selected = snapshot.selected_overlay
    if selected is None:
        return False
    overlay = next((item for item in snapshot.overlays if item.path == selected), None)
    return overlay is not None and overlay.username is None


def plan_config_init(args: argparse.Namespace) -> InitPlan:
    """Return a read-only, migration-aware owner identity plan."""
    del args
    snapshot = config_core.get_agent_owner_config_snapshot()
    if snapshot.status == "complete" and snapshot.owner is not None:
        owner = snapshot.owner
        return InitPlan(
            command="config",
            label="Config",
            summary=(
                f"owner identity is configured as {owner.username}@{owner.machine_name}"
            ),
            actions=(),
        )

    blockers: list[str] = []
    if not snapshot.repairable:
        blockers.append(snapshot.detail)
    elif (
        _selected_overlay_missing_username(snapshot)
        and len(snapshot.existing_usernames) > 1
    ):
        blockers.append(
            "conflicting existing usernames prevent automatic reuse: "
            f"{', '.join(snapshot.existing_usernames)}; resolve the overlays or "
            "set the selected overlay's `id.username` explicitly"
        )

    actions: list[InitAction] = []
    if not blockers and snapshot.selected_overlay is not None:
        operation: InitOperation = (
            "update" if snapshot.selected_overlay.exists() else "create"
        )
        detail = {
            "legacy": (
                "migrate deprecated top-level `machine_name`, add the stable "
                "per-user `id.username`, and preserve unrelated YAML"
            ),
            "partial": (
                "complete `id.username` and `id.machine_name` in the selected "
                "machine overlay"
            ),
            "invalid": "repair invalid nested owner identity values",
            "missing_overlay": (
                "create the selected machine overlay with `id.username` and "
                "`id.machine_name`"
            ),
        }.get(snapshot.status, "repair the selected owner identity overlay")
        actions.append(
            InitAction(
                path=snapshot.selected_overlay,
                operation=operation,
                detail=detail,
            )
        )

    selector_path = machine_name_path()
    if not blockers and snapshot.status in {
        "missing_selector",
        "invalid_selector",
        "selector_mismatch",
    }:
        actions.append(
            InitAction(
                path=selector_path,
                operation="update" if selector_path.exists() else "create",
                detail=(
                    "select an existing machine overlay or create a new one; "
                    f"{snapshot.detail}"
                ),
            )
        )

    summary = (
        f"legacy owner identity requires migration: {snapshot.detail}"
        if snapshot.status == "legacy"
        else snapshot.detail
    )
    return InitPlan(
        command="config",
        label="Config",
        summary=summary,
        actions=tuple(actions),
        blockers=tuple(blockers),
    )


def _hostname_suggestion() -> str:
    """Return the schema-safe lowercase hostname suggestion."""
    return re.sub(r"[^a-z_]", "_", socket.gethostname().lower())


def _machine_name_suggestion(names: tuple[str, ...]) -> str:
    """Return the machine name offered as the default when re-selecting.

    A machine overlay is materialized only on the machine it belongs to, so a
    lone declared name is this machine's own identity. Offering it re-adopts
    that overlay after a lost selector or a renamed host, instead of minting a
    second identity for one machine from a hostname that no longer matches how
    the overlay was named. The rejected selector is never offered back, because
    accepting it would rebuild the same mismatch it is being repaired from.
    """
    if len(names) == 1:
        return names[0]
    return _hostname_suggestion()


def _prompt_machine_name(
    args: argparse.Namespace,
    names: tuple[str, ...],
    *,
    suggestion: str | None = None,
) -> str | None:
    if names:
        print(f"Existing machine names: {', '.join(names)}")
    else:
        print("No existing machine overlays were found.")

    input_func = getattr(args, "_init_input_func", None) or input
    suggested = suggestion or _hostname_suggestion()
    prompt = "Machine name"
    if suggested:
        prompt += f" [{suggested}]"
    prompt += ": "

    while True:
        try:
            answer = input_func(prompt)
        except (EOFError, StopIteration):
            print(
                "error: owner identity initialization received no input",
                file=sys.stderr,
            )
            return None
        except KeyboardInterrupt:
            print("\nerror: owner identity initialization cancelled", file=sys.stderr)
            return None

        candidate = answer.strip() or suggested
        if config_core.is_valid_machine_name(candidate):
            return candidate
        print(
            "Invalid machine name. Use only lowercase letters and underscores "
            "(pattern: ^[a-z_]+$).",
            file=sys.stderr,
        )


def _prompt_username(args: argparse.Namespace) -> str | None:
    input_func = getattr(args, "_init_input_func", None) or input
    print(_USERNAME_CONTRACT)
    while True:
        try:
            candidate = input_func("SASE username: ").strip()
        except (EOFError, StopIteration):
            print(
                "error: owner identity initialization received no username",
                file=sys.stderr,
            )
            return None
        except KeyboardInterrupt:
            print("\nerror: owner identity initialization cancelled", file=sys.stderr)
            return None
        try:
            validate_agent_username(candidate)
        except (RuntimeError, ValueError) as exc:
            print(f"Invalid SASE username: {exc}", file=sys.stderr)
            continue
        return candidate


def _confirm_existing_username(
    args: argparse.Namespace,
    username: str,
    machine_name: str,
) -> bool:
    input_func = getattr(args, "_init_input_func", None) or input
    print(_USERNAME_CONTRACT)
    prompt = (
        f"Reuse existing username '{username}' for machine '{machine_name}'? [y/N] "
    )
    try:
        answer = input_func(prompt)
    except (EOFError, StopIteration):
        answer = ""
    except KeyboardInterrupt:
        print(file=sys.stderr)
        answer = ""
    return answer.strip().lower() in {"y", "yes"}


def _machine_hood_collisions(machine_name: str) -> tuple[str, ...]:
    """Return durable agent names occupying the proposed top-level hood."""
    from sase.agent.names import get_reserved_agent_names

    prefixes = (f"{machine_name}.", f"{machine_name}--")
    return tuple(
        sorted(
            name
            for name in get_reserved_agent_names()
            if name == machine_name or name.startswith(prefixes)
        )
    )


def _confirm_registry_collision(
    args: argparse.Namespace,
    machine_name: str,
    collisions: tuple[str, ...],
) -> bool:
    if not collisions:
        return True
    input_func = getattr(args, "_init_input_func", None) or input
    joined = ", ".join(collisions)
    prompt = (
        f"Machine hood '{machine_name}' collides with registered agent name(s): "
        f"{joined}. Continue anyway? [y/N] "
    )
    try:
        answer = input_func(prompt)
    except (EOFError, StopIteration):
        answer = ""
    except KeyboardInterrupt:
        print(file=sys.stderr)
        answer = ""
    if answer.strip().lower() in {"y", "yes"}:
        return True
    print("Owner identity initialization cancelled.", file=sys.stderr)
    return False


def _read_overlay_text(write_path: Path, target_path: Path) -> str:
    """Read the actual destination, falling back to its applied target."""
    source = write_path if write_path.exists() else target_path
    if not source.exists():
        return ""
    return source.read_text(encoding="utf-8")


def _write_identity_overlay(
    target_path: Path,
    *,
    username: str,
    machine_name: str,
    use_chezmoi: bool,
) -> tuple[Path, bool]:
    """Write identity, materializing a missing destination from the target."""
    write_path = resolve_write_path(str(target_path), use_chezmoi=use_chezmoi)
    if write_path is None:  # pragma: no cover - a concrete target was supplied.
        raise ConfigEditError("machine overlay has no writable destination")
    destination_exists = write_path.exists()
    current_text = _read_overlay_text(write_path, target_path)
    updated_text = set_key(current_text, ("id", "username"), username)
    updated_text = set_key(
        updated_text,
        ("id", "machine_name"),
        machine_name,
    )
    updated_text = unset_key(updated_text, ("machine_name",))
    if destination_exists and updated_text == current_text:
        return write_path, False
    write_path.parent.mkdir(parents=True, exist_ok=True)
    write_path.write_text(updated_text, encoding="utf-8")
    return write_path, True


def _write_machine_selector(machine_name: str) -> Path:
    path = machine_name_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{machine_name}\n", encoding="utf-8")
    return path


def _deploy_machine_overlay(
    paths: Sequence[Path],
    args: argparse.Namespace,
) -> int:
    if defer_chezmoi_paths(paths, chezmoi_home=config_core.CHEZMOI_HOME):
        return 0
    return deploy_to_chezmoi(
        paths,
        ChezmoiDeployBehavior(
            command_label=_COMMAND_LABEL,
            commit_message="chore: initialize SASE owner identity",
            auto_commit_type="init",
            chezmoi_home=config_core.CHEZMOI_HOME,
            no_commit=getattr(args, "no_commit", False),
            no_push=getattr(args, "no_push", False),
            no_apply=getattr(args, "no_apply", False),
        ),
    )


def _ensure_machine_overlay_ignored(
    overlay_write_path: Path,
) -> Path | None:
    entry = chezmoi_target_entry(
        overlay_write_path,
        chezmoi_home=config_core.CHEZMOI_HOME,
    )
    if entry is None:
        return None
    hostname = chezmoi_hostname()
    if hostname is None:
        print(
            "config init: could not determine the chezmoi hostname; "
            f"add a `.chezmoiignore` guard for {entry} manually",
            file=sys.stderr,
        )
        return None
    return ensure_machine_ignore_entry(
        chezmoi_home=config_core.CHEZMOI_HOME,
        entry=entry,
        hostname=hostname,
    )


def _overlay_for_machine(
    snapshot: config_core.AgentOwnerConfigSnapshot,
    machine_name: str,
) -> tuple[config_core.RawOverlayIdentity | None, str | None]:
    matching = [
        overlay
        for overlay in snapshot.overlays
        if overlay.discriminator == machine_name
    ]
    if len(matching) > 1:
        paths = ", ".join(str(item.path) for item in matching)
        return None, (
            f"duplicate identity overlays declare machine '{machine_name}': {paths}"
        )
    if matching:
        overlay = matching[0]
        if overlay.nested_legacy_conflict:
            return None, (
                f"{overlay.path} has conflicting nested and legacy machine names"
            )
        return overlay, None

    target = overlay_config_path(machine_name)
    conventional = next(
        (overlay for overlay in snapshot.overlays if overlay.path == target),
        None,
    )
    if conventional is not None and conventional.declares_machine_overlay:
        return None, (
            f"{target} declares machine '{conventional.discriminator}', not "
            f"'{machine_name}'"
        )
    return conventional, None


def _configured_username(
    overlay: config_core.RawOverlayIdentity | None,
) -> str | None:
    if overlay is None or overlay.username is None:
        return None
    try:
        validate_agent_username(overlay.username)
    except (RuntimeError, ValueError):
        return None
    return overlay.username


def _choose_username(
    args: argparse.Namespace,
    snapshot: config_core.AgentOwnerConfigSnapshot,
    overlay: config_core.RawOverlayIdentity | None,
    machine_name: str,
) -> str | None:
    configured = _configured_username(overlay)
    if configured is not None:
        return configured

    candidates = snapshot.existing_usernames
    if len(candidates) > 1:
        print(
            "error: conflicting existing usernames cannot be chosen "
            f"automatically: {', '.join(candidates)}; set `id.username` in "
            f"{overlay.path if overlay is not None else overlay_config_path(machine_name)}",
            file=sys.stderr,
        )
        return None
    if len(candidates) == 1 and _confirm_existing_username(
        args,
        candidates[0],
        machine_name,
    ):
        return candidates[0]
    return _prompt_username(args)


def run_config_init(args: argparse.Namespace) -> int:
    """Interactively create, migrate, or repair the selected owner identity."""
    if getattr(args, "check", False):
        from .init_onboarding import run_init_check
        from .init_registry import InitCommandSpec

        return run_init_check(
            args,
            specs=(
                InitCommandSpec(
                    name="config",
                    label="Config",
                    plan=plan_config_init,
                    run=run_config_init,
                ),
            ),
        )

    snapshot = config_core.get_agent_owner_config_snapshot()
    if snapshot.status == "complete" and snapshot.owner is not None:
        owner = snapshot.owner
        print(
            "Owner identity is already configured as "
            f"{owner.username}@{owner.machine_name}."
        )
        return 0
    if not snapshot.repairable:
        print(
            f"error: cannot initialize owner identity: {snapshot.detail}",
            file=sys.stderr,
        )
        return 1

    stdin: TextIO = getattr(args, "_init_stdin", None) or sys.stdin
    if not stdin.isatty():
        print(
            "error: owner identity initialization requires an interactive TTY; "
            "run `sase config init` in a terminal",
            file=sys.stderr,
        )
        return 1

    machine_name = snapshot.selector
    if machine_name is None or snapshot.status == "selector_mismatch":
        names = _existing_machine_names()
        machine_name = _prompt_machine_name(
            args,
            names,
            suggestion=_machine_name_suggestion(names),
        )
    if machine_name is None:
        return 1

    overlay, overlay_error = _overlay_for_machine(snapshot, machine_name)
    if overlay_error is not None:
        print(f"error: {overlay_error}", file=sys.stderr)
        return 1
    username = _choose_username(args, snapshot, overlay, machine_name)
    if username is None:
        return 1

    try:
        collisions = _machine_hood_collisions(machine_name)
    except Exception as exc:  # noqa: BLE001 - registry failures are user-facing.
        print(
            f"error: failed to inspect the agent-name registry: {exc}", file=sys.stderr
        )
        return 1
    if not _confirm_registry_collision(args, machine_name, collisions):
        return 1

    try:
        use_chezmoi = config_core.get_use_chezmoi()
    except Exception as exc:  # noqa: BLE001 - config failures are user-facing.
        print(f"error: failed to resolve config write policy: {exc}", file=sys.stderr)
        return 1

    target_path = (
        overlay.path if overlay is not None else overlay_config_path(machine_name)
    )
    overlay_write_path: Path | None = None
    overlay_changed = False
    try:
        overlay_write_path, overlay_changed = _write_identity_overlay(
            target_path,
            username=username,
            machine_name=machine_name,
            use_chezmoi=use_chezmoi,
        )
        selector_path = _write_machine_selector(machine_name)
    except Exception as exc:  # noqa: BLE001 - write/YAML failures are user-facing.
        config_core.clear_config_cache()
        print(f"error: failed to initialize owner identity: {exc}", file=sys.stderr)
        return 1

    config_core.clear_config_cache()
    if overlay_changed:
        print(f"Updated owner identity overlay: {overlay_write_path}")
    print(
        f"Selected owner '{username}' on machine '{machine_name}' in {selector_path}."
    )

    if use_chezmoi and overlay_changed and overlay_write_path is not None:
        deploy_paths = [overlay_write_path]
        try:
            ignore_path = _ensure_machine_overlay_ignored(overlay_write_path)
        except OSError as exc:
            print(
                f"error: failed to update the chezmoi ignore list: {exc}",
                file=sys.stderr,
            )
            return 1
        if ignore_path is not None:
            print(f"Restricted {machine_name} overlay to this machine in {ignore_path}")
            deploy_paths.append(ignore_path)
        return _deploy_machine_overlay(deploy_paths, args)
    return 0


__all__ = ["plan_config_init", "run_config_init"]
