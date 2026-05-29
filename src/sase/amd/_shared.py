"""Shared helpers for AMD initialization modules."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from sase.main.init_plan import InitAction, InitPlan

from .constants import PROVIDER_SHIM_CONTENT, PROVIDER_SHIM_FILES

COMMAND_LABEL = "init amd"


@dataclass(frozen=True)
class PlannedWrite:
    path: Path
    content: str
    action: InitAction


@dataclass(frozen=True)
class AmdInitPlan:
    plan: InitPlan
    writes: tuple[PlannedWrite, ...]


@dataclass(frozen=True)
class AmdLongMemoryDescriptionUpdate:
    """Planned frontmatter update for a long-term memory file."""

    path: Path
    content: str


@dataclass(frozen=True)
class AmdMemorySyncPlan:
    """Files needed to keep AMD-managed memory blocks synchronized."""

    title: str | None
    agents_content: str | None
    description_updates: tuple[AmdLongMemoryDescriptionUpdate, ...]
    blockers: tuple[str, ...] = ()


def read_text(path: Path) -> tuple[str | None, str | None]:
    try:
        return path.read_text(encoding="utf-8"), None
    except OSError as exc:
        return None, f"{path}: failed to read file: {exc}"
    except UnicodeDecodeError as exc:
        return None, f"{path}: failed to decode as UTF-8: {exc}"


def load_yaml_mapping(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    text, read_error = read_text(path)
    if read_error is not None or text is None:
        return None, read_error
    try:
        data = yaml.safe_load(text or "")
    except yaml.YAMLError as exc:
        return None, f"{path}: failed to parse YAML: {exc}"
    if data is None:
        return None, None
    if not isinstance(data, dict):
        return None, f"{path}: expected a YAML mapping at the top level"
    return data, None


def _is_shim_text(text: str) -> bool:
    return text.strip() == PROVIDER_SHIM_CONTENT.strip()


def provider_statuses(root: Path) -> tuple[dict[Path, str], tuple[str, ...]]:
    statuses: dict[Path, str] = {}
    errors: list[str] = []
    for filename in PROVIDER_SHIM_FILES:
        path = root / filename
        if not path.exists():
            statuses[path] = "missing"
            continue
        text, error = read_text(path)
        if error is not None or text is None:
            statuses[path] = "custom"
            errors.append(error or f"{path}: failed to read file")
            continue
        if text == PROVIDER_SHIM_CONTENT:
            statuses[path] = "exact_shim"
        elif _is_shim_text(text):
            statuses[path] = "shim"
        else:
            statuses[path] = "custom"
    return statuses, tuple(errors)


def _action_for_write(path: Path, content: str, *, detail: str) -> InitAction | None:
    if not path.exists():
        return InitAction(path=path, operation="create", detail=detail)
    current, _error = read_text(path)
    if current == content:
        return None
    return InitAction(path=path, operation="overwrite", detail=detail)


def planned_write(path: Path, content: str, *, detail: str) -> PlannedWrite | None:
    action = _action_for_write(path, content, detail=detail)
    if action is None:
        return None
    return PlannedWrite(path=path, content=content, action=action)


def provider_shim_writes(root: Path) -> tuple[PlannedWrite, ...]:
    writes: list[PlannedWrite] = []
    for filename in PROVIDER_SHIM_FILES:
        write = planned_write(
            root / filename,
            PROVIDER_SHIM_CONTENT,
            detail="provider instruction shim",
        )
        if write is not None:
            writes.append(write)
    return tuple(writes)
