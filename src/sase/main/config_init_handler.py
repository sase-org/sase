"""Interactive machine-identity initialization for SASE configuration."""

from __future__ import annotations

import argparse
import re
import socket
import sys
from pathlib import Path
from typing import TextIO

from sase.config import core as config_core
from sase.config._edit_types import ConfigEditError
from sase.config._edit_yaml import set_key
from sase.config.targets import overlay_config_path, resolve_write_path
from sase.core.paths import machine_name_path

from ._init_chezmoi_deploy import (
    ChezmoiDeployBehavior,
    defer_chezmoi_paths,
    deploy_to_chezmoi,
)
from .init_plan import InitAction, InitPlan

_COMMAND_LABEL = "config init"


def _existing_machine_names() -> tuple[str, ...]:
    """Return valid identities declared by any raw user overlay."""
    return config_core.discover_machine_names()


def _configured_machine_name() -> str | None:
    """Return the current identity only when selector and config agree."""
    return config_core.get_machine_name()


def plan_config_init(args: argparse.Namespace) -> InitPlan:
    """Return a read-only plan for machine identity initialization."""
    del args
    configured = _configured_machine_name()
    if configured is not None:
        return InitPlan(
            command="config",
            label="Config",
            summary=f"machine identity is configured as {configured}",
            actions=(),
        )

    names = _existing_machine_names()
    selector_path = machine_name_path()
    choices = f" Existing choices: {', '.join(names)}." if names else ""
    return InitPlan(
        command="config",
        label="Config",
        summary="choose or create the machine-local identity",
        actions=(
            InitAction(
                path=selector_path,
                operation="update" if selector_path.exists() else "create",
                detail=(
                    f"select an existing machine overlay or create a new one.{choices}"
                ),
            ),
        ),
    )


def _hostname_suggestion() -> str:
    """Return the schema-safe lowercase hostname suggestion."""
    return re.sub(r"[^a-z_]", "_", socket.gethostname().lower())


def _prompt_machine_name(
    args: argparse.Namespace, names: tuple[str, ...]
) -> str | None:
    if names:
        print(f"Existing machine names: {', '.join(names)}")
    else:
        print("No existing machine overlays were found.")

    input_func = getattr(args, "_init_input_func", None) or input
    suggestion = _hostname_suggestion()
    prompt = "Machine name"
    if suggestion:
        prompt += f" [{suggestion}]"
    prompt += ": "

    while True:
        try:
            answer = input_func(prompt)
        except EOFError:
            print(
                "error: machine identity initialization received no input",
                file=sys.stderr,
            )
            return None
        except KeyboardInterrupt:
            print("\nerror: machine identity initialization cancelled", file=sys.stderr)
            return None

        candidate = answer.strip() or suggestion
        if config_core.is_valid_machine_name(candidate):
            return candidate
        print(
            "Invalid machine name. Use only lowercase letters and underscores "
            "(pattern: ^[a-z_]+$).",
            file=sys.stderr,
        )


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
    except EOFError:
        answer = ""
    except KeyboardInterrupt:
        print(file=sys.stderr)
        answer = ""
    if answer.strip().lower() in {"y", "yes"}:
        return True
    print("Machine identity initialization cancelled.", file=sys.stderr)
    return False


def _read_overlay_text(write_path: Path, target_path: Path) -> str:
    """Read the actual destination, falling back to its applied target."""
    source = write_path if write_path.exists() else target_path
    if not source.exists():
        return ""
    return source.read_text(encoding="utf-8")


def _write_new_machine_overlay(machine_name: str, *, use_chezmoi: bool) -> Path:
    target_path = overlay_config_path(machine_name)
    write_path = resolve_write_path(str(target_path), use_chezmoi=use_chezmoi)
    if write_path is None:  # pragma: no cover - a concrete target was supplied.
        raise ConfigEditError("machine overlay has no writable destination")
    current_text = _read_overlay_text(write_path, target_path)
    updated_text = set_key(current_text, ("machine_name",), machine_name)
    write_path.parent.mkdir(parents=True, exist_ok=True)
    write_path.write_text(updated_text, encoding="utf-8")
    return write_path


def _write_machine_selector(machine_name: str) -> Path:
    path = machine_name_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{machine_name}\n", encoding="utf-8")
    return path


def _deploy_machine_overlay(path: Path, args: argparse.Namespace) -> int:
    if defer_chezmoi_paths((path,), chezmoi_home=config_core.CHEZMOI_HOME):
        return 0
    return deploy_to_chezmoi(
        (path,),
        ChezmoiDeployBehavior(
            command_label=_COMMAND_LABEL,
            commit_message="chore: initialize SASE machine config",
            auto_commit_type="init",
            chezmoi_home=config_core.CHEZMOI_HOME,
            no_commit=getattr(args, "no_commit", False),
            no_push=getattr(args, "no_push", False),
            no_apply=getattr(args, "no_apply", False),
        ),
    )


def run_config_init(args: argparse.Namespace) -> int:
    """Interactively select or create the machine-local SASE identity."""
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

    configured = _configured_machine_name()
    if configured is not None:
        print(f"Machine identity is already configured as {configured}.")
        return 0

    stdin: TextIO = getattr(args, "_init_stdin", None) or sys.stdin
    if not stdin.isatty():
        print(
            "error: machine identity initialization requires an interactive TTY; "
            "run `sase config init` in a terminal",
            file=sys.stderr,
        )
        return 1

    names = _existing_machine_names()
    machine_name = _prompt_machine_name(args, names)
    if machine_name is None:
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
    overlay_write_path: Path | None = None
    try:
        if machine_name not in names:
            overlay_write_path = _write_new_machine_overlay(
                machine_name,
                use_chezmoi=use_chezmoi,
            )
        selector_path = _write_machine_selector(machine_name)
    except Exception as exc:  # noqa: BLE001 - write/YAML failures are user-facing.
        config_core.clear_config_cache()
        print(f"error: failed to initialize machine identity: {exc}", file=sys.stderr)
        return 1

    config_core.clear_config_cache()
    if overlay_write_path is not None:
        print(f"Created machine overlay: {overlay_write_path}")
    print(f"Selected machine identity '{machine_name}' in {selector_path}.")

    if use_chezmoi and overlay_write_path is not None:
        return _deploy_machine_overlay(overlay_write_path, args)
    return 0


__all__ = ["plan_config_init", "run_config_init"]
