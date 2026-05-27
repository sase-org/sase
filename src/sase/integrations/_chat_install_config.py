"""Configuration and workspace resolution for chat install/update jobs."""

from __future__ import annotations

from pathlib import Path

from sase.config.core import load_merged_config
from sase.core.paths import sase_projects_dir

from ._chat_install_models import ChatInstallConfig


def load_chat_install_config() -> ChatInstallConfig:
    """Read and normalize the ``chat_install`` merged-config section."""
    raw = load_merged_config().get("chat_install", {})
    if not isinstance(raw, dict):
        raw = {}

    command = raw.get("command", "")
    sync_workspace = raw.get("sync_workspace", True)
    timeout_seconds = raw.get("timeout_seconds", 900)
    restart_attempts = raw.get("restart_attempts", 3)

    return ChatInstallConfig(
        command=command.strip() if isinstance(command, str) else "",
        sync_workspace=bool(sync_workspace),
        timeout_seconds=_positive_int(timeout_seconds, 900),
        restart_attempts=_positive_int(restart_attempts, 3),
    )


def resolve_primary_workspace_for_chat_install() -> Path | None:
    """Resolve the registered SASE project workspace used as install/sync cwd."""
    registered_workspace = _resolve_registered_sase_workspace()
    if registered_workspace is not None:
        return registered_workspace

    from sase.bead.workspace import resolve_primary_workspace

    return resolve_primary_workspace()


def _resolve_registered_sase_workspace() -> Path | None:
    """Resolve the registered ``sase`` project workspace without consulting CWD."""
    from sase.ace.changespec.project_spec_path import preferred_project_spec_path

    project_dir = sase_projects_dir() / "sase"
    project_file = Path(preferred_project_spec_path(str(project_dir), "sase"))

    from sase.workspace_provider.utils import parse_workspace_dir

    workspace_dir = parse_workspace_dir(str(project_file))
    if not workspace_dir:
        return None

    workspace = Path(workspace_dir).expanduser()
    if not workspace.is_dir():
        return None
    return workspace


def _positive_int(value: object, default: int) -> int:
    if not isinstance(value, int | str | bytes | bytearray):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default
