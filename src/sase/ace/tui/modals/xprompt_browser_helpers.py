"""Helper utilities for the XPrompt browser modal."""

from __future__ import annotations

import importlib.resources
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from sase.ace.tui.widgets.xprompt_arg_assist import append_input_args
from sase.main.plugin_discovery import discover_plugin_resources
from sase.xprompt.loader import (
    get_sase_package_default_xprompts_dir,
    get_sase_package_xprompts_dir,
)
from sase.xprompt.workflow_models import Workflow


@dataclass
class BrowserItem:
    """An xprompt item in the browser list."""

    name: str
    workflow: Workflow
    source_category: str
    source_path: str | None
    display_path: str
    is_editable: bool
    item_type: str  # "xprompt" or "workflow"
    kind: str  # "xprompt", "embeddable_workflow", or "standalone_workflow"
    insertion: str


def classify_source(source_path: str | None) -> tuple[str, str, bool]:
    """Classify a source path into (category_label, display_path, is_editable)."""
    if source_path is None:
        return "Built-in", "", True

    home = str(Path.home())
    cwd = str(Path.cwd())
    sase_pkg_dirs = [
        str(get_sase_package_xprompts_dir()),
        str(get_sase_package_default_xprompts_dir()),
    ]

    # Plugin sources: "plugin:module_name/filename.md" (xprompts/ dirs)
    # or "plugin_config:module_name" (default_config.yml)
    if source_path.startswith("plugin:") or source_path.startswith("plugin_config:"):
        if source_path.startswith("plugin_config:"):
            module_name = source_path.removeprefix("plugin_config:")
        else:
            module_part = source_path.removeprefix("plugin:")
            module_name = (
                module_part.split("/")[0] if "/" in module_part else module_part
            )
        short_name = module_name.replace("_", "-")
        return f"Plugin ({short_name})", source_path, True

    # Built-in default config xprompts
    if source_path == "default_config":
        return "Built-in", "sase default_config.yml", True

    # Config sources: user sase.yml
    if source_path == "config":
        return "User sase.yml", "~/.config/sase/sase.yml", True

    # Config overlay sources: sase_*.yml files
    if source_path.startswith("config_overlay:"):
        filename = source_path.removeprefix("config_overlay:")
        return "User sase.yml", f"~/.config/sase/{filename}", True

    # Local sase.yml in CWD
    if source_path == "local_config":
        return "Local sase.yml", "./sase.yml", True

    # Project-local sase.yml loaded via get_all_project_local_prompts()
    if source_path.startswith("project_local_config:"):
        proj = source_path.removeprefix("project_local_config:")
        return f"Project ({proj}) sase.yml", f"~/.sase/projects/{proj}/sase.yml", True

    # Inside sase package (built-in)
    if any(source_path.startswith(pkg_dir) for pkg_dir in sase_pkg_dirs):
        return "Built-in", source_path.replace(home, "~"), True

    # Project-specific: ~/.config/sase/xprompts/{proj}/
    project_prefix = os.path.join(home, ".config", "sase", "xprompts")
    if source_path.startswith(project_prefix + "/"):
        remainder = source_path[len(project_prefix) + 1 :]
        proj = remainder.split("/")[0]
        return f"Project ({proj})", source_path.replace(home, "~"), True

    # CWD directories
    cwd_hidden = os.path.join(cwd, ".xprompts")
    cwd_visible = os.path.join(cwd, "xprompts")
    if source_path.startswith(cwd_hidden + "/"):
        return "CWD .xprompts/", source_path.replace(cwd, "."), True
    if source_path.startswith(cwd_visible + "/"):
        return "CWD xprompts/", source_path.replace(cwd, "."), True

    # Home directories
    home_hidden = os.path.join(home, ".xprompts")
    home_visible = os.path.join(home, "xprompts")
    if source_path.startswith(home_hidden + "/"):
        return "Home ~/.xprompts/", source_path.replace(home, "~"), True
    if source_path.startswith(home_visible + "/"):
        return "Home ~/xprompts/", source_path.replace(home, "~"), True

    # Fallback
    return "Other", source_path.replace(home, "~"), True


def resolve_source_to_file_path(source_path: str | None) -> str | None:
    """Resolve a source path identifier to an actual filesystem path.

    Handles plugin, config, and built-in source path formats used by the
    xprompt loader, returning the real file path that can be opened in an editor.
    """
    if source_path is None:
        return None

    # plugin:module_name/filename → resolve xprompts dir via importlib.resources
    if source_path.startswith("plugin:"):
        remainder = source_path.removeprefix("plugin:")
        if "/" in remainder:
            module_name, filename = remainder.split("/", 1)
        else:
            return None
        for module in discover_plugin_resources("sase_xprompts"):
            if module.__name__ == module_name:
                try:
                    xprompts_dir = importlib.resources.files(module).joinpath(
                        "xprompts"
                    )
                    return str(Path(str(xprompts_dir)) / filename)
                except (TypeError, AttributeError):
                    pass
        return None

    # plugin_config:module_name → resolve default_config.yml via importlib.resources
    if source_path.startswith("plugin_config:"):
        module_name = source_path.removeprefix("plugin_config:")
        for module in discover_plugin_resources("sase_config"):
            if module.__name__ == module_name:
                try:
                    ref = importlib.resources.files(module).joinpath(
                        "default_config.yml"
                    )
                    return str(ref)
                except (TypeError, AttributeError):
                    pass
        return None

    # default_config → sase's bundled default_config.yml
    if source_path == "default_config":
        try:
            return str(importlib.resources.files("sase").joinpath("default_config.yml"))
        except Exception:
            return None

    # local_config → ./sase.yml in CWD
    if source_path == "local_config":
        return str(Path.cwd() / "sase.yml")

    # project_local_config:{project} → project's workspace sase.yml
    if source_path.startswith("project_local_config:"):
        project_name = source_path.removeprefix("project_local_config:")
        from sase.xprompt.loader import get_known_project_workspaces

        workspaces = get_known_project_workspaces()
        ws_dir = workspaces.get(project_name)
        if ws_dir:
            return str(ws_dir / "sase.yml")
        return None

    # config → user sase.yml
    if source_path == "config":
        return str(Path.home() / ".config" / "sase" / "sase.yml")

    # config_overlay:filename → user sase config overlay
    if source_path.startswith("config_overlay:"):
        filename = source_path.removeprefix("config_overlay:")
        return str(Path.home() / ".config" / "sase" / filename)

    # Regular filesystem path — return as-is
    return source_path


def get_git_root(file_path: str) -> str | None:
    """Return the git repo root for the given file, or None if not in a repo."""
    directory = str(Path(file_path).parent)
    try:
        result = subprocess.run(
            ["git", "-C", directory, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except OSError:
        pass
    return None


def has_git_changes(git_root: str, file_path: str) -> bool:
    """Check if the file has uncommitted changes (staged or unstaged)."""
    try:
        result = subprocess.run(
            ["git", "-C", git_root, "status", "--porcelain", "--", file_path],
            capture_output=True,
            text=True,
            check=False,
        )
        return bool(result.stdout.strip())
    except OSError:
        return False
