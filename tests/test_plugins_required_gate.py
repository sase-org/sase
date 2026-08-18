"""Trusted PluginsRequired gate construction, presentation, and command coverage."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sase.notification_gates.registry import adapter_for_kind
from sase.notifications import pending_actions
from sase.notifications.priority import is_priority
from sase.notifications.store import load_notifications
from sase.plugins.operations import AlreadyInstalled, NotUvTool
from sase.plugins.required_gate import (
    PLUGINS_REQUIRED_PREVIEW_PATH,
    create_plugins_required_gate,
    execute_plugins_required_gate_command,
)
from sase.uv_tool.errors import UvToolError
from sase.uv_tool.runner import ChangeKind

from tests.test_plugins_required_gate_helpers import (
    missing_entry,
    plugins_required_spec,
)


def test_plugins_required_gate_builds_canonical_spec_preview_and_pending_action(
    gate_home: Path,
) -> None:
    del gate_home
    missing = [
        missing_entry(),
        missing_entry(
            requirement="sase-research-artifacts>=0.2",
            name="sase-research-artifacts",
            kind="version_mismatch",
            install_command="sase plugin install sase-research-artifacts",
            message=(
                "required plugin `sase-research-artifacts>=0.2` is installed "
                "as 0.1.0; run `sase plugin install sase-research-artifacts`"
            ),
        ),
    ]
    gate = create_plugins_required_gate(
        request_id="plugins-required-canonical",
        project="sase",
        project_label="sase",
        missing=missing,
        producer={"chop": "plugins_required"},
    )

    request = json.loads(gate.request_path.read_text(encoding="utf-8"))
    assert request["kind"] == "plugins_required"
    assert request["query"] == "install OR dismiss"
    assert request["branches"] == [["install"], ["dismiss"]]
    assert request["primary_branch"] == ["install"]
    assert request["payload"] == {
        "project": "sase",
        "project_label": "sase",
        "missing": missing,
    }
    assert [
        (option["id"], option["label"], option["feedback"])
        for option in request["options"]
    ] == [
        ("install", "Install", "disabled"),
        ("dismiss", "Dismiss", "disabled"),
    ]
    assert request["presentation"]["sender"] == "plugin"
    assert request["presentation"]["icon"] == "📦"
    assert request["presentation"]["title"] == "Missing required plugins — sase"
    assert request["presentation"]["notes"] == ["2 required plugins to install · sase"]
    assert request["presentation"]["tags"] == ["plugin", "required"]
    assert request["presentation"]["panel"] == "plugins"
    assert request["presentation"]["panel_icon"] == "📦"
    assert "origin_agent" not in request["presentation"]
    preview = (gate.bundle_path / PLUGINS_REQUIRED_PREVIEW_PATH).read_text(
        encoding="utf-8"
    )
    assert "# Missing required plugins" in preview
    assert "**Project:** sase" in preview
    assert "successful install restarts axe" in preview
    assert "sase-github" in preview
    assert "sase-research-artifacts" in preview
    assert "`sase plugin install sase-github`" in preview

    [notification] = load_notifications()
    assert notification.action == "PluginsRequired"
    assert notification.sender == "plugin"
    assert notification.icon == "📦"
    assert notification.tags == ["plugin", "required"]
    assert notification.action_data["panel"] == "plugins"
    assert notification.action_data["panel_icon"] == "📦"
    assert is_priority(notification)
    [entry] = pending_actions.read_pending_action_store()["actions"].values()
    assert entry["action_kind"] == "plugins_required"
    adapter = adapter_for_kind("plugins_required")
    assert adapter.auto_policy == "forbidden"
    assert adapter.generic_form is True
    assert adapter.neutral_only is True
    assert adapter.default_feedback == "disabled"
    assert adapter.display_title == "Required Plugins"
    assert adapter.action == "PluginsRequired"


def _run_execute(
    option_id: str,
    raw: object,
    *,
    requirements: list[str] | None = None,
    plan_install_fn: Any | None = None,
    execute_install_fn: Any | None = None,
) -> tuple[int, str, str]:
    stdin = io.StringIO(raw if isinstance(raw, str) else json.dumps(raw) + "\n")
    stdout = io.StringIO()
    stderr = io.StringIO()
    old_stdin, old_stdout, old_stderr = sys.stdin, sys.stdout, sys.stderr
    sys.stdin, sys.stdout, sys.stderr = stdin, stdout, stderr
    try:
        code = execute_plugins_required_gate_command(
            option_id,
            requirements,
            plan_install_fn=plan_install_fn,
            execute_install_fn=execute_install_fn,
        )
    finally:
        sys.stdin, sys.stdout, sys.stderr = old_stdin, old_stdout, old_stderr
    return code, stdout.getvalue(), stderr.getvalue()


def test_dismiss_command_emits_typed_result() -> None:
    code, stdout, stderr = _run_execute("dismiss", {})
    assert code == 0
    assert stderr == ""
    assert json.loads(stdout) == {"action": "dismiss"}


def test_dismiss_command_rejects_unknown_field() -> None:
    code, _stdout, stderr = _run_execute("dismiss", {"winner": "enabled"})
    assert code == 2
    assert "unknown field id" in stderr


def test_install_command_fails_closed_when_not_uv_tool() -> None:
    message = (
        "sase is not running from a `uv tool` install "
        "(it is running from /tmp/venv). "
        "`sase update` and `sase plugin install/update` only work when sase "
        "was installed with `uv tool install sase`. Install sase with "
        "`uv tool install sase`."
    )

    def plan(_name: str) -> NotUvTool:
        return NotUvTool(_Message(message))

    code, stdout, stderr = _run_execute(
        "install",
        {},
        requirements=["sase-github"],
        plan_install_fn=plan,
    )
    assert code == 2
    assert stdout == ""
    assert message in stderr


def test_install_command_installs_each_name_and_reports_changed() -> None:
    from sase.plugins.operations import InstallReady, ResolvedSpec
    from sase.uv_tool.receipt import Requirement

    planned: list[str] = []
    executed: list[str] = []

    def plan_ready(name: str) -> InstallReady:
        planned.append(name)
        spec = ResolvedSpec(
            requirement=Requirement.from_spec(name),
            display_name=name,
            source="catalog",
        )
        return InstallReady(spec=spec, argv=["uv", "tool", "install", name])

    def execute(plan_obj: object) -> object:
        name = plan_obj.spec.requirement.name  # type: ignore[attr-defined]
        executed.append(name)
        return SimpleNamespace(
            change_set=SimpleNamespace(changes=[SimpleNamespace(kind=ChangeKind.ADDED)])
        )

    code, stdout, stderr = _run_execute(
        "install",
        {},
        requirements=["sase-github", "sase-research-artifacts"],
        plan_install_fn=plan_ready,
        execute_install_fn=execute,
    )
    assert code == 0
    assert stderr == ""
    assert planned == ["sase-github", "sase-research-artifacts"]
    assert executed == ["sase-github", "sase-research-artifacts"]
    assert json.loads(stdout) == {
        "action": "install",
        "changed": True,
        "installed": ["sase-github", "sase-research-artifacts"],
    }


def test_install_command_treats_already_installed_as_unchanged() -> None:
    from sase.plugins.operations import ResolvedSpec
    from sase.uv_tool.receipt import Requirement

    def plan(name: str) -> AlreadyInstalled:
        return AlreadyInstalled(
            spec=ResolvedSpec(
                requirement=Requirement.from_spec(name),
                display_name=name,
                source="catalog",
            )
        )

    executed: list[object] = []
    code, stdout, stderr = _run_execute(
        "install",
        {},
        requirements=["sase-github"],
        plan_install_fn=plan,
        execute_install_fn=executed.append,
    )
    assert code == 0
    assert stderr == ""
    assert executed == []
    assert json.loads(stdout) == {
        "action": "install",
        "changed": False,
        "installed": ["sase-github"],
    }


def test_install_command_rejects_empty_requirement_list() -> None:
    code, _stdout, stderr = _run_execute("install", {}, requirements=[])
    assert code == 2
    assert "at least one plugin name" in stderr


def test_command_rejects_non_object_stdin() -> None:
    code, _stdout, stderr = _run_execute("dismiss", [1, 2])
    assert code == 2
    assert "must be an object" in stderr


def test_command_rejects_unknown_option() -> None:
    code, _stdout, stderr = _run_execute("keep", {})
    assert code == 2
    assert "unsupported plugins required option" in stderr


def test_spec_bakes_install_names_into_the_command(gate_home: Path) -> None:
    del gate_home
    from sase.notification_gates.service import create_gate

    spec = plugins_required_spec(
        request_id="plugins-required-baked",
        missing=[
            missing_entry(),
            missing_entry(
                requirement="sase-research-artifacts",
                name="sase-research-artifacts",
            ),
        ],
    )
    gate = create_gate(spec)
    script = (gate.bundle_path / "commands" / "install").read_text(encoding="utf-8")
    assert "sase-github" in script
    assert "sase-research-artifacts" in script
    dismiss = (gate.bundle_path / "commands" / "dismiss").read_text(encoding="utf-8")
    assert "dismiss" in dismiss
    assert "sase-github" not in dismiss


class _Message(UvToolError):
    """Minimal uv-tool error carrying a rendered message."""
