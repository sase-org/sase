"""Helper utilities for the Macro browser modal."""

from __future__ import annotations

import importlib.resources
import subprocess
from dataclasses import dataclass
from pathlib import Path

from sase.ace.tui.widgets.macro_arg_assist import append_input_args
from sase.content_layout import (
    discover_project_root,
    display_path,
    resolve_home_layout,
    resolve_project_config_read_path,
    resolve_project_layout,
)
from sase.main.plugin_discovery import (
    LEGACY_PLUGIN_MACROS_DIR,
    discover_macro_plugin_modules,
    discover_plugin_resources,
    macro_plugin_definition_dirname,
)
from sase.project_display_names import project_display_name_for
from sase.macro.loader import (
    get_sase_package_default_macros_dir,
    get_sase_package_macros_dir,
)
from sase.macro.project_identity import (
    canonical_macro_project,
    known_project_namespaces,
)
from sase.macro.workflow_models import Workflow

from .macro_location_modal import (
    MACRO_HOME_DIR_LABEL,
    MACRO_PROJECT_DIR_LABEL,
)


@dataclass
class BrowserItem:
    """A macro item in the browser list."""

    name: str
    workflow: Workflow
    source_category: str
    source_path: str | None
    display_path: str
    is_editable: bool
    item_type: str  # "macro" or "workflow"
    kind: str  # "macro", "embeddable_workflow", "standalone_workflow", or "memory"
    insertion: str


def classify_source(source_path: str | None) -> tuple[str, str, bool]:
    """Classify a source path into (category_label, display_path, is_editable)."""
    if source_path is None:
        return "Built-in", "", False

    home_path = Path.home()
    project_root = discover_project_root() or Path.cwd()
    project_layout = resolve_project_layout(project_root, home_root=home_path)
    home_layout = resolve_home_layout(home_path)
    home = str(home_path)
    sase_pkg_dirs = [
        str(get_sase_package_macros_dir()),
        str(get_sase_package_default_macros_dir()),
    ]

    # Plugin sources: "plugin:module_name/filename.md" (macros/ dirs)
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
        return f"Plugin ({short_name})", source_path, False

    # Built-in default config macros
    if source_path == "default_config":
        return "Built-in", "sase default_config.yml", False

    # Config sources: user sase.yml
    if source_path == "config":
        return "User sase.yml", "~/.config/sase/sase.yml", True

    # Config overlay sources: sase_*.yml files
    if source_path.startswith("config_overlay:"):
        filename = source_path.removeprefix("config_overlay:")
        return "User sase.yml", f"~/.config/sase/{filename}", True

    # Local sase.yml in CWD
    if source_path == "local_config":
        config_path = resolve_project_config_read_path(project_root)
        display = (
            display_path(config_path, project_root=project_root, home_root=home_path)
            if config_path is not None
            else "sase/sase.yml"
        )
        return "Project sase.yml", display, True

    # Project-local sase.yml loaded via get_all_project_local_prompts()
    if source_path.startswith("project_local_config:"):
        proj = source_path.removeprefix("project_local_config:")
        project_label = project_display_name_for(proj)
        return f"Project ({project_label}) sase.yml", "sase/sase.yml", True

    # Inside sase package (built-in)
    if any(source_path.startswith(pkg_dir) for pkg_dir in sase_pkg_dirs):
        return "Built-in", source_path.replace(home, "~"), False

    path = Path(source_path)
    project_macros_candidates: list[Path] = list(project_layout.macros.candidates)
    if project_layout.xprompts.write_path not in project_macros_candidates:
        project_macros_candidates.append(project_layout.xprompts.write_path)
    for candidate in project_macros_candidates:
        try:
            path.relative_to(candidate)
        except ValueError:
            continue
        label = (
            MACRO_PROJECT_DIR_LABEL
            if candidate == project_layout.macros.write_path
            else "Project macros/ (legacy)"
        )
        return label, display_path(path, project_root=project_root), True

    for candidate in project_layout.memory.candidates:
        try:
            path.relative_to(candidate)
        except ValueError:
            continue
        label = (
            "Project sase/memory/"
            if candidate == project_layout.memory.write_path
            else "Project memory/ (legacy)"
        )
        return label, display_path(path, project_root=project_root), True

    home_macros_candidates: list[Path] = list(home_layout.macros.candidates)
    if home_layout.xprompts.write_path not in home_macros_candidates:
        home_macros_candidates.append(home_layout.xprompts.write_path)
    for candidate in home_macros_candidates:
        try:
            relative = path.relative_to(candidate)
        except ValueError:
            continue
        if len(relative.parts) > 1:
            project_label = project_display_name_for(relative.parts[0])
            return (
                f"Project home ({project_label})",
                display_path(path, home_root=home_path),
                True,
            )
        label = (
            MACRO_HOME_DIR_LABEL
            if candidate == home_layout.macros.write_path
            else "Home macros/ (legacy)"
        )
        return label, display_path(path, home_root=home_path), True

    for candidate in home_layout.memory.candidates:
        try:
            path.relative_to(candidate)
        except ValueError:
            continue
        label = (
            "Home ~/sase/memory/"
            if candidate == home_layout.memory.write_path
            else "Home memory/ (legacy)"
        )
        return label, display_path(path, home_root=home_path), True

    legacy_project_home = home_path / ".config" / "sase" / LEGACY_PLUGIN_MACROS_DIR
    try:
        relative = path.relative_to(legacy_project_home)
    except ValueError:
        pass
    else:
        project_name = relative.parts[0] if relative.parts else "unknown"
        project_label = project_display_name_for(project_name)
        return (
            f"Project home ({project_label}, legacy)",
            display_path(path, home_root=home_path),
            True,
        )

    # Fallback
    return "Other", source_path.replace(home, "~"), True


# Source-path identifiers (used by the macro loader) that name a YAML
# config/workflow file rather than a standalone ``.md`` prompt-part file.
_YAML_CONFIG_SOURCE_IDS = frozenset({"config", "local_config", "default_config"})
_YAML_CONFIG_SOURCE_PREFIXES = (
    "config_overlay:",
    "project_local_config:",
    "plugin_config:",
)


def is_yaml_backed_source(source_path: str | None) -> bool:
    """Return True when *source_path* is backed by a YAML config/workflow file.

    Covers both regular ``.yml`` / ``.yaml`` filesystem paths (workflow files
    and any plugin ``.yml`` entry) and the loader's config source identifiers
    that resolve to YAML: the user/local sase.yml (``config`` / ``local_config``),
    config overlays (``config_overlay:``), per-project sase.yml
    (``project_local_config:``), the bundled default config (``default_config``),
    and a plugin's bundled default config (``plugin_config:``).

    Uses only the cheap source-path identifier -- no disk access or file
    resolution -- so it is safe to call on every navigation / key event. A
    ``None`` source (a programmatic built-in with no file) is treated as
    non-YAML.
    """
    if source_path is None:
        return False
    if source_path in _YAML_CONFIG_SOURCE_IDS:
        return True
    if source_path.startswith(_YAML_CONFIG_SOURCE_PREFIXES):
        return True
    return source_path.lower().endswith((".yml", ".yaml"))


def resolve_source_to_file_path(source_path: str | None) -> str | None:
    """Resolve a source path identifier to an actual filesystem path.

    Handles plugin, config, and built-in source path formats used by the
    macro loader, returning the real file path that can be opened in an editor.
    """
    if source_path is None:
        return None

    # plugin:module_name/filename → resolve macros dir via importlib.resources
    if source_path.startswith("plugin:"):
        remainder = source_path.removeprefix("plugin:")
        if "/" in remainder:
            module_name, filename = remainder.split("/", 1)
        else:
            return None
        for module in discover_macro_plugin_modules():
            if module.__name__ == module_name:
                try:
                    resource_dir = macro_plugin_definition_dirname(module)
                    if resource_dir is None:
                        continue
                    macros_dir = importlib.resources.files(module).joinpath(
                        resource_dir
                    )
                    return str(Path(str(macros_dir)) / filename)
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

    # local_config → project sase/sase.yml (legacy root fallback is display-only)
    if source_path == "local_config":
        project_root = discover_project_root() or Path.cwd()
        path = resolve_project_config_read_path(project_root)
        return str(path) if path is not None else None

    # project_local_config:{project} → project's workspace sase.yml
    if source_path.startswith("project_local_config:"):
        project_name = source_path.removeprefix("project_local_config:")
        namespace = canonical_macro_project(project_name) or project_name
        ws_dir = known_project_namespaces().get(namespace)
        if ws_dir:
            path = resolve_project_config_read_path(
                ws_dir,
                label=f"project config for {namespace}",
            )
            return str(path or resolve_project_layout(ws_dir).config.write_path)
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
