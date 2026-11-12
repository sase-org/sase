"""Launcher-row helpers for the healer relaunch.

Public helpers live in this already-private module so the relaunch claim
can use them without importing ``_``-prefixed names across modules.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.agent.auto_restart._healer_common import HealerTarget, read_json


def is_launcher_row(
    target: HealerTarget,
    *,
    done: Mapping[str, Any],
    meta: Mapping[str, Any],
) -> bool:
    """Return whether a failed row died before it acquired a workflow name."""

    for payload in (meta, done):
        for key in ("name", "workflow_name"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return False
    return target.agent_name == target.artifacts_dir.name


def _launcher_explicit_directives(prompt: str) -> list[Any]:
    """Return explicit ``%id`` directives from a single-segment prompt."""
    from sase.agent.launch_validation import iter_explicit_launch_name_directives

    try:
        return list(iter_explicit_launch_name_directives(prompt))
    except Exception:
        return []


def launcher_intended_names(prompt: str) -> list[str]:
    """Return concrete non-force explicit names from the launcher prompt."""
    names: list[str] = []
    for directive in _launcher_explicit_directives(prompt):
        if getattr(directive, "name_template", False):
            continue
        if getattr(directive, "force_reuse", False):
            continue
        name = getattr(directive, "name", "")
        if isinstance(name, str) and name and name not in names:
            names.append(name)
    return names


def launcher_has_force_reuse(prompt: str) -> bool:
    """Return whether the launcher prompt requests forced name reuse."""
    for directive in _launcher_explicit_directives(prompt):
        if getattr(directive, "force_reuse", False):
            return True
    return False


def _launcher_owned_planned_names(prompt: str, failed_dir: Path) -> list[str]:
    """Return prompt names whose planned reservation is owned by the failed row."""
    from sase.agent.names import planned_registered_name_belongs_to_artifact

    owned: list[str] = []
    for name in launcher_intended_names(prompt):
        try:
            if planned_registered_name_belongs_to_artifact(name, failed_dir):
                owned.append(name)
        except Exception:
            continue
    return owned


def prepare_launcher_reservation(prompt: str, target: HealerTarget) -> list[str]:
    """Release the failed row's owned planned names and re-validate the guard.

    Discovery uses the existing owner-checked reservation primitive, so a
    foreign or live owner's name is never touched. Ownership and liveness
    are rechecked at this mutation boundary: the failed row must still be a
    failed row on disk, every previously owned name must still belong to it,
    and the real launch-name guard must pass after the release. Any change
    raises with an actionable message so the caller settles terminally
    instead of launching a duplicate or consuming unrelated state.
    """
    from sase.agent.launch_validation import validate_launch_name_requests
    from sase.agent.names import (
        planned_registered_name_belongs_to_artifact,
        release_planned_registered_name,
    )

    owned = _launcher_owned_planned_names(prompt, target.artifacts_dir)

    done_path = target.artifacts_dir / "done.json"
    try:
        if not done_path.is_file():
            raise RuntimeError(
                "failed row is gone; not stealing its former name reservation"
            )
        fresh = read_json(done_path) or {}
        if str(fresh.get("outcome", "")) != "failed":
            raise RuntimeError(
                "failed row is no longer failed; not reusing its reservation"
            )
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"could not recheck failed row liveness: {exc}") from exc

    for name in list(owned):
        try:
            still = planned_registered_name_belongs_to_artifact(
                name, target.artifacts_dir
            )
        except Exception as exc:
            raise RuntimeError(
                f"could not recheck reservation for '{name}': {exc}"
            ) from exc
        if not still:
            raise RuntimeError(
                f"planned reservation for '{name}' changed owner before "
                "relaunch; not stealing another row's reservation"
            )

    for name in owned:
        try:
            release_planned_registered_name(name, target.artifacts_dir)
        except Exception as exc:
            raise RuntimeError(
                f"could not release owned reservation '{name}': {exc}"
            ) from exc

    try:
        validate_launch_name_requests([prompt])
    except Exception as exc:
        raise RuntimeError(
            f"launch guard still refuses after releasing owned reservation: {exc}"
        ) from exc
    return owned


def launcher_project_cwd(project: str) -> Path:
    """Find the primary checkout used to submit a prompt for *project*."""

    if project == "home":
        cwd = Path.home()
    else:
        from sase.core.paths import sase_projects_dir
        from sase.core.project_lifecycle_facade import list_project_records

        record = next(
            (
                item
                for item in list_project_records(
                    sase_projects_dir(), "all", include_home=True
                )
                if item.project_name == project
            ),
            None,
        )
        if record is None or not record.workspace_dir:
            raise LookupError(f"project '{project}' has no configured workspace")
        cwd = Path(record.workspace_dir).expanduser()
    if not cwd.is_dir():
        raise FileNotFoundError(f"project workspace does not exist: {cwd}")
    return cwd


def launch_launcher_prompt(
    prompt: str, extra_env: dict[str, str], cwd: Path | None
) -> Any:
    """Resubmit the original launcher prompt through the normal launch funnel."""

    import contextlib
    from types import SimpleNamespace

    from sase.agent.launcher import launch_agents_from_cwd

    if cwd is None:
        raise RuntimeError("launcher project workspace was not resolved")
    # The regular project launch path atomically claims a free numbered slot.
    # Leave the failed row's hold and artifacts untouched; its slot remains
    # occupied while the replacement claims a different one.
    with contextlib.chdir(cwd):
        results = launch_agents_from_cwd(
            prompt,
            extra_env=extra_env,
            origin="generated",
            source_surface="auto_restart",
        )
    if not results:
        raise RuntimeError("agent launch produced no results")
    launched_dir = getattr(results[0], "artifacts_dir", None) or None
    return SimpleNamespace(status="ok", launched_artifacts_dir=launched_dir, error=None)


__all__ = [
    "is_launcher_row",
    "launch_launcher_prompt",
    "launcher_has_force_reuse",
    "launcher_intended_names",
    "launcher_project_cwd",
    "prepare_launcher_reservation",
]
