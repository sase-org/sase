"""The request shape and option commands of the PluginsRequired gate.

Everything here defines what a PluginsRequired gate *is*: its constants, the
one request spec the adapter accepts, the option command wrappers, and the
result schema each option must emit. Gate validation rebuilds these from the
persisted payload and compares, so each helper must stay a pure function of
its arguments.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from sase.notification_gates.entrypoints import gate_command_entrypoint
from sase.plugins._required_gate_preview import (
    plugins_required_presentation_note,
    render_plugins_required_preview,
)
from sase.project_display_names import project_display_name_for

PluginsRequiredAction = Literal["install", "dismiss"]
PluginsRequiredMissingKind = Literal["missing", "version_mismatch"]

PLUGINS_REQUIRED_KIND = "plugins_required"
PLUGINS_REQUIRED_CONTINUATION_MODE = "plugins_required"
PLUGINS_REQUIRED_QUERY = "install OR dismiss"
PLUGINS_REQUIRED_INSTALL_OPTION_ID: PluginsRequiredAction = "install"
PLUGINS_REQUIRED_DISMISS_OPTION_ID: PluginsRequiredAction = "dismiss"
PLUGINS_REQUIRED_OPTION_IDS: tuple[PluginsRequiredAction, ...] = (
    PLUGINS_REQUIRED_INSTALL_OPTION_ID,
    PLUGINS_REQUIRED_DISMISS_OPTION_ID,
)
PLUGINS_REQUIRED_PRIMARY_BRANCH = (PLUGINS_REQUIRED_INSTALL_OPTION_ID,)
PLUGINS_REQUIRED_PREVIEW_PATH = "plugins.md"
PLUGINS_REQUIRED_COMMAND_PATHS: dict[PluginsRequiredAction, str] = {
    option_id: f"commands/{option_id}" for option_id in PLUGINS_REQUIRED_OPTION_IDS
}
PLUGINS_REQUIRED_OPTION_LABELS: dict[PluginsRequiredAction, str] = {
    PLUGINS_REQUIRED_INSTALL_OPTION_ID: "Install",
    PLUGINS_REQUIRED_DISMISS_OPTION_ID: "Dismiss",
}
PLUGINS_REQUIRED_OPTION_ICONS: dict[PluginsRequiredAction, str] = {
    PLUGINS_REQUIRED_INSTALL_OPTION_ID: "⬇",
    PLUGINS_REQUIRED_DISMISS_OPTION_ID: "✕",
}
PLUGINS_REQUIRED_MISSING_KINDS: tuple[PluginsRequiredMissingKind, ...] = (
    "missing",
    "version_mismatch",
)


def plugins_required_missing_payload(
    issues: Sequence[Any],
) -> list[dict[str, str]]:
    """Return the structured missing-set payload for one project's gate."""
    entries: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for issue in issues:
        kind = str(_attr(issue, "kind"))
        requirement = str(_attr(issue, "requirement") or "")
        name = str(_attr(issue, "name") or "")
        install_command = str(_attr(issue, "install_command") or "")
        message = str(_attr(issue, "message") or "")
        identity = (kind, requirement)
        if identity in seen:
            continue
        seen.add(identity)
        entries.append(
            {
                "requirement": requirement,
                "name": name,
                "kind": kind,
                "install_command": install_command,
                "message": message,
            }
        )
    entries.sort(key=lambda item: (item["kind"], item["requirement"], item["name"]))
    return entries


def plugins_required_install_queries(missing: Sequence[Any]) -> tuple[str, ...]:
    """Return unique plugin names to install, in payload order."""
    names: list[str] = []
    seen: set[str] = set()
    for item in missing:
        name = str(_attr(item, "name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return tuple(names)


def build_plugins_required_gate_spec(
    *,
    request_id: str,
    project: str,
    missing: Sequence[Any],
    project_label: str | None = None,
    producer: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the only request shape accepted by the PluginsRequired adapter."""
    roster = plugins_required_missing_payload(missing)
    label = (
        project_label
        if project_label is not None and project_label.strip()
        else project_display_name_for(project)
    )
    payload = {
        "project": project,
        "project_label": label,
        "missing": roster,
    }
    payload_view = _PayloadView(
        project=project,
        project_label=label,
        missing=roster,
    )
    return {
        "schema_version": 3,
        "kind": PLUGINS_REQUIRED_KIND,
        "request_id": request_id,
        "producer": dict(producer or {}),
        "continuation_mode": PLUGINS_REQUIRED_CONTINUATION_MODE,
        "payload": payload,
        "presentation": {
            "sender": "plugin",
            "icon": "📦",
            "title": f"Missing required plugins — {label}",
            "notes": [plugins_required_presentation_note(payload_view)],
            "tags": ["plugin", "required"],
            "panel": "plugins",
            "panel_icon": "📦",
            "files": [PLUGINS_REQUIRED_PREVIEW_PATH],
            "preview": PLUGINS_REQUIRED_PREVIEW_PATH,
        },
        "query": PLUGINS_REQUIRED_QUERY,
        "primary_branch": list(PLUGINS_REQUIRED_PRIMARY_BRANCH),
        "options": [
            plugins_required_option_spec(option_id)
            for option_id in PLUGINS_REQUIRED_OPTION_IDS
        ],
        "resources": [
            *[
                {
                    "path": PLUGINS_REQUIRED_COMMAND_PATHS[option_id],
                    "role": "command",
                    "content": plugins_required_gate_command_script(
                        option_id,
                        requirements=plugins_required_install_queries(roster),
                    ),
                }
                for option_id in PLUGINS_REQUIRED_OPTION_IDS
            ],
            {
                "path": PLUGINS_REQUIRED_PREVIEW_PATH,
                "role": "preview",
                "content": render_plugins_required_preview(payload_view),
            },
        ],
        "auto": False,
    }


def plugins_required_option_spec(option_id: PluginsRequiredAction) -> dict[str, Any]:
    """Return the only spec one PluginsRequired option is accepted with."""
    return {
        "id": option_id,
        "label": PLUGINS_REQUIRED_OPTION_LABELS[option_id],
        "icon": PLUGINS_REQUIRED_OPTION_ICONS[option_id],
        "command": {"argv": [PLUGINS_REQUIRED_COMMAND_PATHS[option_id]]},
        "result_schema": plugins_required_result_schema(option_id),
        "feedback": "disabled",
    }


def plugins_required_result_schema(action: PluginsRequiredAction) -> dict[str, Any]:
    if action == PLUGINS_REQUIRED_INSTALL_OPTION_ID:
        return {
            "type": "object",
            "required": ["action", "installed", "changed"],
            "properties": {
                "action": {"const": action},
                "installed": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                },
                "changed": {"type": "boolean"},
            },
            "additionalProperties": False,
        }
    return {
        "type": "object",
        "required": ["action"],
        "properties": {"action": {"const": action}},
        "additionalProperties": False,
    }


def plugins_required_gate_command_script(
    option_id: str,
    *,
    requirements: Sequence[str] = (),
) -> str:
    """Return the only command wrapper accepted by the PluginsRequired adapter.

    The wrapper imports from :mod:`sase.plugins.required_gate` because the
    script text is persisted into every gate bundle and revalidated byte for
    byte. Install bakes the requirement names so a forged command cannot
    install a plugin the preview never offered.
    """
    if option_id == PLUGINS_REQUIRED_INSTALL_OPTION_ID:
        names = list(requirements)
        return (
            f"#!{sys.executable}\n"
            "from sase.plugins.required_gate import "
            "execute_plugins_required_gate_command\n"
            "raise SystemExit(execute_plugins_required_gate_command("
            f"{option_id!r}, {names!r}))\n"
        )
    return (
        f"#!{sys.executable}\n"
        "from sase.plugins.required_gate import "
        "execute_plugins_required_gate_command\n"
        f"raise SystemExit(execute_plugins_required_gate_command({option_id!r}))\n"
    )


@gate_command_entrypoint
def execute_plugins_required_gate_command(
    option_id: str,
    requirements: Sequence[str] | None = None,
    *,
    plan_install_many_fn: Any | None = None,
    execute_install_many_fn: Any | None = None,
) -> int:
    """Validate command input and run Install, or emit the Dismiss result.

    Install preflights the baked names through one bounded batch planner and
    executes at most one reconstructed ``uv`` install before emitting a result,
    so a not-``uv tool`` environment (or any other install failure) leaves the
    gate pending instead of reporting a phantom success. AXE restart is left to
    the host effect after the response is persisted.
    """
    try:
        raw_input = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"invalid command input: {exc}", file=sys.stderr)
        return 2
    if not isinstance(raw_input, dict):
        print("plugins required command input must be an object", file=sys.stderr)
        return 2
    extra = [key for key in raw_input if key != "feedback"]
    if extra:
        print(f"unknown field id: {extra[0]}", file=sys.stderr)
        return 2
    if option_id == PLUGINS_REQUIRED_DISMISS_OPTION_ID:
        print(json.dumps({"action": option_id}, sort_keys=True))
        return 0
    if option_id != PLUGINS_REQUIRED_INSTALL_OPTION_ID:
        print(f"unsupported plugins required option: {option_id}", file=sys.stderr)
        return 2
    names = [name.strip() for name in (requirements or ()) if str(name).strip()]
    if not names:
        print("install requires at least one plugin name", file=sys.stderr)
        return 2
    return _execute_install(
        names,
        plan_install_many_fn=plan_install_many_fn,
        execute_install_many_fn=execute_install_many_fn,
    )


def _execute_install(
    names: Sequence[str],
    *,
    plan_install_many_fn: Any | None,
    execute_install_many_fn: Any | None,
) -> int:
    from sase.plugins.operations import (
        InstallManyNothing,
        InstallManyReady,
        NotUvTool,
        execute_install_many,
        plan_install_many,
    )
    from sase.uv_tool.errors import UvToolError

    plan_fn = (
        plan_install_many if plan_install_many_fn is None else plan_install_many_fn
    )
    run_fn = (
        execute_install_many
        if execute_install_many_fn is None
        else execute_install_many_fn
    )
    planned_names = tuple(names)
    try:
        plan = plan_fn(planned_names)
    except Exception as exc:  # noqa: BLE001 - keep the gate pending.
        print(str(exc), file=sys.stderr)
        return 2
    if isinstance(plan, NotUvTool):
        print(str(plan.error), file=sys.stderr)
        return 2
    if isinstance(plan, InstallManyNothing):
        if not plan.skipped or not _only_already_installed_skips(plan.skipped):
            _print_skipped_install_error(plan.skipped[0] if plan.skipped else None)
            return 2
        _print_install_result(planned_names, changed=False)
        return 0
    if not isinstance(plan, InstallManyReady):
        print("unable to plan required plugin install", file=sys.stderr)
        return 2
    if not _only_already_installed_skips(plan.skipped):
        _print_skipped_install_error(plan.skipped[0] if plan.skipped else None)
        return 2

    try:
        outcome = run_fn(plan)
    except UvToolError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - keep the gate pending.
        print(str(exc), file=sys.stderr)
        return 2
    _print_install_result(planned_names, changed=_install_outcome_changed(outcome))
    return 0


def _only_already_installed_skips(skipped: Sequence[Any]) -> bool:
    return all(getattr(item, "reason", "") == "already installed" for item in skipped)


def _print_skipped_install_error(skipped: Any | None) -> None:
    if skipped is None:
        print("unable to plan required plugin install", file=sys.stderr)
        return
    query = str(getattr(skipped, "query", "") or "plugin")
    reason = str(getattr(skipped, "reason", "") or "skipped")
    if reason == "not found":
        print(
            f"plugin {query!r} was not found in the catalog; "
            f"run `sase plugin install {query}`",
            file=sys.stderr,
        )
        return
    print(f"unable to plan install for {query!r}: {reason}", file=sys.stderr)


def _install_outcome_changed(outcome: Any) -> bool:
    from sase.uv_tool.runner import ChangeKind

    change_set = getattr(outcome, "change_set", None)
    if change_set is None:
        return True
    return any(
        getattr(change, "kind", None) is not ChangeKind.UNCHANGED
        for change in getattr(change_set, "changes", ())
    )


def _print_install_result(installed: Sequence[str], *, changed: bool) -> None:
    print(
        json.dumps(
            {
                "action": PLUGINS_REQUIRED_INSTALL_OPTION_ID,
                "installed": list(installed),
                "changed": changed,
            },
            sort_keys=True,
        )
    )


def _attr(item: Any, name: str) -> Any:
    if isinstance(item, Mapping):
        return item.get(name)
    return getattr(item, name, None)


class _PayloadView:
    """Duck-typed payload used while building a spec from caller arguments."""

    __slots__ = ("missing", "project", "project_label")

    def __init__(
        self,
        *,
        project: str,
        project_label: str,
        missing: list[dict[str, str]],
    ) -> None:
        self.project = project
        self.project_label = project_label
        self.missing = missing
