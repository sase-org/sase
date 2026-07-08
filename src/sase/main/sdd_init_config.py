"""Project-local config updates for explicit SDD initialization."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import yaml  # type: ignore[import-untyped]

from .init_plan import InitAction

_SDD_INIT_CONFIG = "sdd:\n  version_controlled: true\n"
_STORAGE_VALUES = frozenset({"auto", "in_tree", "local", "separate_repo"})


class SddInitConfigError(ValueError):
    """Raised when ``sase sdd init`` cannot safely update local config."""


@dataclass(frozen=True)
class _SddInitConfigPlan:
    """Read-only plan for the SDD init config update."""

    path: Path
    action: InitAction | None = None
    blockers: tuple[str, ...] = ()


def _resolve_sdd_init_config_path(
    path: str | Path | None = None, *, cwd: Path | None = None
) -> Path:
    """Resolve the project-local ``sase.yml`` path for an SDD init target."""
    from sase.sdd._paths import resolve_sdd_readme_path

    path_arg = str(path) if path is not None else None
    sdd_root = resolve_sdd_readme_path(path_arg, cwd=cwd).parent
    if sdd_root.name == "sdd" and sdd_root.parent.name == ".sase":
        return (sdd_root.parent.parent / "sase.yml").resolve()
    return (sdd_root.parent / "sase.yml").resolve()


def resolve_sdd_init_config_path(
    path: str | Path | None = None, *, cwd: Path | None = None
) -> Path:
    """Resolve the project-local ``sase.yml`` path for an SDD init target."""
    return _resolve_sdd_init_config_path(path, cwd=cwd)


def plan_sdd_init_config(
    path: str | Path | None = None,
    *,
    cwd: Path | None = None,
    storage: str | None = None,
) -> _SddInitConfigPlan:
    """Return the project-local config action needed for SDD init."""
    _validate_storage(storage)
    config_path = _resolve_sdd_init_config_path(path, cwd=cwd)
    if not config_path.exists():
        return _SddInitConfigPlan(
            path=config_path,
            action=InitAction(
                path=config_path,
                operation="create",
                detail=_config_action_detail(storage),
            ),
        )

    loaded = _load_config_mapping(config_path)
    if loaded.blocker is not None:
        return _SddInitConfigPlan(path=config_path, blockers=(loaded.blocker,))

    sdd_config = loaded.data.get("sdd")
    if (
        storage is None
        and isinstance(sdd_config, dict)
        and (
            sdd_config.get("version_controlled") is True
            or sdd_config.get("storage") == "in_tree"
        )
    ):
        return _SddInitConfigPlan(path=config_path)
    if (
        storage is not None
        and isinstance(sdd_config, dict)
        and sdd_config.get("storage") == storage
        and "version_controlled" not in sdd_config
    ):
        return _SddInitConfigPlan(path=config_path)

    return _SddInitConfigPlan(
        path=config_path,
        action=InitAction(
            path=config_path,
            operation="update",
            detail=_config_action_detail(storage),
        ),
    )


def write_sdd_init_config(
    path: str | Path | None = None,
    *,
    cwd: Path | None = None,
    storage: str | None = None,
) -> Path:
    """Ensure project-local config opts into version-controlled SDD."""
    _validate_storage(storage)
    plan = plan_sdd_init_config(path, cwd=cwd, storage=storage)
    if plan.blockers:
        raise SddInitConfigError("\n".join(plan.blockers))
    if plan.action is None:
        return plan.path

    if not plan.path.exists():
        plan.path.parent.mkdir(parents=True, exist_ok=True)
        plan.path.write_text(_initial_config_text(storage), encoding="utf-8")
        return plan.path

    text = plan.path.read_text(encoding="utf-8")
    loaded = _load_config_mapping(plan.path, text=text)
    if loaded.blocker is not None:
        raise SddInitConfigError(loaded.blocker)
    plan.path.write_text(
        _updated_config_text(text, loaded.data, storage=storage),
        encoding="utf-8",
    )
    return plan.path


@dataclass(frozen=True)
class _LoadedConfig:
    data: dict[Any, Any]
    blocker: str | None = None


def _load_config_mapping(path: Path, *, text: str | None = None) -> _LoadedConfig:
    try:
        config_text = path.read_text(encoding="utf-8") if text is None else text
    except OSError as exc:
        return _LoadedConfig({}, f"cannot read {path}: {exc}")

    try:
        parsed = (
            {} if _config_text_is_empty(config_text) else yaml.safe_load(config_text)
        )
    except yaml.YAMLError as exc:
        return _LoadedConfig({}, f"invalid YAML in {path}: {exc}")

    if parsed is None:
        return _LoadedConfig({}, f"{path} must contain a YAML mapping")
    if not isinstance(parsed, dict):
        return _LoadedConfig({}, f"{path} must contain a YAML mapping")

    sdd_config = parsed.get("sdd")
    if (
        sdd_config is None
        and "sdd" in parsed
        and not _has_empty_sdd_section(config_text)
    ):
        return _LoadedConfig({}, f"{path} has non-mapping sdd config")
    if sdd_config is not None and not isinstance(sdd_config, dict):
        return _LoadedConfig({}, f"{path} has non-mapping sdd config")

    return _LoadedConfig(parsed)


def _config_text_is_empty(text: str) -> bool:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped in {"---", "..."}:
            continue
        return False
    return True


def _has_empty_sdd_section(text: str) -> bool:
    lines = text.splitlines(keepends=True)
    sdd_range = _find_top_level_sdd_range(lines)
    if sdd_range is None:
        return False

    start, end = sdd_range
    rest = _top_level_sdd_rest(lines[start]).strip()
    if rest and not rest.startswith("#"):
        return False
    return all(
        not line.strip() or line.strip().startswith("#")
        for line in lines[start + 1 : end]
    )


def _validate_storage(storage: str | None) -> None:
    if storage is not None and storage not in _STORAGE_VALUES:
        raise SddInitConfigError(
            "sdd.storage must be one of: auto, in_tree, local, separate_repo"
        )


def _config_action_detail(storage: str | None) -> str:
    if storage is None:
        return "enable sdd.version_controlled"
    return f"set sdd.storage to {storage}"


def _initial_config_text(storage: str | None) -> str:
    if storage is None:
        return _SDD_INIT_CONFIG
    return f"sdd:\n  storage: {storage}\n"


def _updated_config_text(
    text: str, data: dict[Any, Any], *, storage: str | None = None
) -> str:
    if storage is not None:
        return _updated_config_text_for_storage(text, data, storage)

    sdd_config = data.get("sdd")
    if not isinstance(sdd_config, dict):
        return _insert_version_controlled_line(text)
    if (
        sdd_config.get("version_controlled") is True
        or sdd_config.get("storage") == "in_tree"
    ):
        return text
    if "version_controlled" in sdd_config:
        replaced = _replace_version_controlled_value(text)
        if replaced is not None:
            return replaced
    return _insert_version_controlled_line(text, sdd_config=sdd_config)


def _updated_config_text_for_storage(
    text: str, data: dict[Any, Any], storage: str
) -> str:
    lines = text.splitlines(keepends=True)
    sdd_range = _find_top_level_sdd_range(lines)
    if sdd_range is None:
        return _append_sdd_section(text, storage=storage)

    sdd_config = data.get("sdd")
    updated_sdd = dict(sdd_config) if isinstance(sdd_config, dict) else {}
    updated_sdd["storage"] = storage
    updated_sdd.pop("version_controlled", None)
    start, end = sdd_range
    return _replace_sdd_block(lines, start, end, updated_sdd)


def _insert_version_controlled_line(
    text: str, *, sdd_config: dict[Any, Any] | None = None
) -> str:
    lines = text.splitlines(keepends=True)
    sdd_range = _find_top_level_sdd_range(lines)
    if sdd_range is None:
        return _append_sdd_section(text)

    start, end = sdd_range
    rest = _top_level_sdd_rest(lines[start]).strip()
    if rest and not rest.startswith("#"):
        if sdd_config is None:
            sdd_config = {}
        updated_sdd = dict(sdd_config)
        updated_sdd["version_controlled"] = True
        return _replace_sdd_block(lines, start, end, updated_sdd)

    newline = _preferred_newline(lines)
    child_indent = _first_child_indent(lines, start, end) or 2
    lines.insert(
        start + 1,
        f"{' ' * child_indent}version_controlled: true{newline}",
    )
    return "".join(lines)


def _replace_version_controlled_value(text: str) -> str | None:
    lines = text.splitlines(keepends=True)
    sdd_range = _find_top_level_sdd_range(lines)
    if sdd_range is None:
        return None

    start, end = sdd_range
    child_indent = _first_child_indent(lines, start, end)
    if child_indent is None:
        return None

    for index in range(start + 1, end):
        if _line_indent(lines[index]) != child_indent:
            continue
        match = re.match(
            r"^(?P<prefix>[ \t]*(?:version_controlled|['\"]version_controlled['\"])\s*:\s*)"
            r"(?P<value>[^#\r\n]*?)"
            r"(?P<suffix>\s*(?:#.*)?)(?P<newline>\r?\n?)$",
            lines[index],
        )
        if match is None:
            continue
        lines[index] = (
            f"{match.group('prefix')}true"
            f"{match.group('suffix')}{match.group('newline')}"
        )
        return "".join(lines)

    return None


def _replace_sdd_block(
    lines: list[str], start: int, end: int, updated_sdd: dict[Any, Any]
) -> str:
    replacement = yaml.safe_dump(
        {"sdd": updated_sdd},
        default_flow_style=False,
        sort_keys=False,
    )
    newline = _preferred_newline(lines)
    replacement = replacement.replace("\n", newline)
    return "".join((*lines[:start], replacement, *lines[end:]))


def _append_sdd_section(text: str, *, storage: str | None = None) -> str:
    config_text = _initial_config_text(storage)
    if not text:
        return config_text
    prefix = text if text.endswith(("\n", "\r")) else f"{text}\n"
    separator = "" if not prefix.strip() else "\n"
    return f"{prefix}{separator}{config_text}"


def _find_top_level_sdd_range(lines: list[str]) -> tuple[int, int] | None:
    for index, line in enumerate(lines):
        if re.match(r"^(?:sdd|['\"]sdd['\"])\s*:", line) is None:
            continue
        end = len(lines)
        for next_index in range(index + 1, len(lines)):
            if _is_top_level_mapping_key(lines[next_index]):
                end = next_index
                break
        return index, end
    return None


def _top_level_sdd_rest(line: str) -> str:
    match = re.match(r"^(?:sdd|['\"]sdd['\"])\s*:(?P<rest>.*?)(?:\r?\n)?$", line)
    return "" if match is None else match.group("rest")


def _is_top_level_mapping_key(line: str) -> bool:
    if not line or line[0].isspace():
        return False
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or stripped in {"---", "..."}:
        return False
    return re.match(r"^(?:[A-Za-z0-9_-]+|['\"][^'\"]+['\"])\s*:", line) is not None


def _first_child_indent(lines: list[str], start: int, end: int) -> int | None:
    for index in range(start + 1, end):
        line = lines[index]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = _line_indent(line)
        if indent > 0:
            return indent
    return None


def _line_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def _preferred_newline(lines: list[str]) -> str:
    for line in lines:
        if line.endswith("\r\n"):
            return "\r\n"
    return "\n"


__all__ = [
    "SddInitConfigError",
    "plan_sdd_init_config",
    "resolve_sdd_init_config_path",
    "write_sdd_init_config",
]
