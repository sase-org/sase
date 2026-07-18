"""Inventory of configured and available AXE chops.

Chops are AXE automation, so their inventory lives with AXE rather than in any
plugin command surface. ``sase axe chop list`` and ``sase axe chop doctor`` both
build on the data collected here.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sase.axe.chop_script_runner import discover_chop_script
from sase.axe.config import AxeConfig, load_axe_config

ConfiguredChopStatus = Literal["configured", "missing"]
AvailableChopSource = Literal["configured_dir", "python_bin", "path"]


@dataclass(frozen=True)
class ConfiguredChopRecord:
    """A chop configured under an AXE lumberjack."""

    lumberjack: str
    name: str
    description: str
    script: str
    env: dict[str, str]
    status: ConfiguredChopStatus
    resolved_path: str | None


@dataclass(frozen=True)
class _AvailableChopScriptRecord:
    """A discovered executable chop script."""

    name: str
    executable: str
    source: AvailableChopSource
    configured: bool


@dataclass(frozen=True)
class ChopInventory:
    """Configured and available chop state."""

    configured_chops: tuple[ConfiguredChopRecord, ...]
    available_scripts: tuple[_AvailableChopScriptRecord, ...]
    chop_script_dirs: tuple[str, ...]
    python_bin_dir: str
    path_dirs: tuple[str, ...]

    @property
    def available_unconfigured(self) -> tuple[_AvailableChopScriptRecord, ...]:
        return tuple(
            script for script in self.available_scripts if not script.configured
        )


def collect_chop_inventory(config: AxeConfig | None = None) -> ChopInventory:
    """Collect configured chops and executable chop scripts.

    Configured script chops are resolved through ``discover_chop_script`` so
    diagnostics match the path AXE will use when it actually runs a chop.
    """
    axe_config = config or load_axe_config()
    configured_chops = _configured_chops(axe_config)
    configured_scripts = {chop.script for chop in configured_chops}
    python_bin_dir = Path(sys.executable).parent
    path_dirs = tuple(_path_dirs())
    available_scripts = _available_chop_scripts(
        search_dirs=axe_config.chop_script_dirs,
        python_bin_dir=python_bin_dir,
        path_dirs=path_dirs,
        configured_scripts=configured_scripts,
    )

    return ChopInventory(
        configured_chops=configured_chops,
        available_scripts=available_scripts,
        chop_script_dirs=tuple(axe_config.chop_script_dirs),
        python_bin_dir=str(python_bin_dir),
        path_dirs=path_dirs,
    )


def chop_inventory_to_dict(inventory: ChopInventory) -> dict[str, Any]:
    """Serialize chop inventory to stable JSON-compatible primitives."""
    return {
        "chop_script_dirs": list(inventory.chop_script_dirs),
        "python_bin_dir": inventory.python_bin_dir,
        "path_dirs": list(inventory.path_dirs),
        "configured": [
            {
                "lumberjack": chop.lumberjack,
                "name": chop.name,
                "description": chop.description,
                "script": chop.script,
                "status": chop.status,
                "resolved_path": chop.resolved_path,
            }
            for chop in inventory.configured_chops
        ],
        "available": [
            {
                "name": script.name,
                "executable": script.executable,
                "source": script.source,
                "configured": script.configured,
            }
            for script in inventory.available_scripts
        ],
        "available_unconfigured": [
            {
                "name": script.name,
                "executable": script.executable,
                "source": script.source,
            }
            for script in inventory.available_unconfigured
        ],
    }


def _configured_chops(axe_config: AxeConfig) -> tuple[ConfiguredChopRecord, ...]:
    records: list[ConfiguredChopRecord] = []
    for lumberjack_name, lumberjack in axe_config.lumberjacks.items():
        for chop in lumberjack.chops:
            script_name = chop.script_name
            script = discover_chop_script(script_name, axe_config.chop_script_dirs)
            records.append(
                ConfiguredChopRecord(
                    lumberjack=lumberjack_name,
                    name=chop.name,
                    description=chop.description,
                    script=script_name,
                    env=dict(chop.env),
                    status="configured" if script is not None else "missing",
                    resolved_path=str(script) if script is not None else None,
                )
            )

    records.sort(key=lambda chop: (chop.lumberjack, chop.name))
    return tuple(records)


def _available_chop_scripts(
    *,
    search_dirs: list[str],
    python_bin_dir: Path,
    path_dirs: tuple[str, ...],
    configured_scripts: set[str],
) -> tuple[_AvailableChopScriptRecord, ...]:
    by_name: dict[str, _AvailableChopScriptRecord] = {}

    for raw_dir in search_dirs:
        dir_path = Path(raw_dir)
        if not dir_path.is_dir():
            continue
        for entry in _iter_dir(dir_path):
            if not _is_executable_file(entry):
                continue
            _add_available(
                by_name,
                name=entry.name,
                executable=entry,
                source="configured_dir",
                configured_scripts=configured_scripts,
            )

    if python_bin_dir.is_dir():
        for entry in _iter_dir(python_bin_dir):
            if entry.name.startswith("sase_chop_") and _is_executable_file(entry):
                _add_available(
                    by_name,
                    name=entry.name,
                    executable=entry,
                    source="python_bin",
                    configured_scripts=configured_scripts,
                )

    seen_path_dirs: set[str] = set()
    for raw_dir in path_dirs:
        if raw_dir in seen_path_dirs:
            continue
        seen_path_dirs.add(raw_dir)
        dir_path = Path(raw_dir)
        if not dir_path.is_dir():
            continue
        for entry in _iter_dir(dir_path):
            if entry.name.startswith("sase_chop_") and _is_executable_file(entry):
                _add_available(
                    by_name,
                    name=entry.name,
                    executable=entry,
                    source="path",
                    configured_scripts=configured_scripts,
                )

    return tuple(sorted(by_name.values(), key=lambda script: script.name))


def _add_available(
    by_name: dict[str, _AvailableChopScriptRecord],
    *,
    name: str,
    executable: Path,
    source: AvailableChopSource,
    configured_scripts: set[str],
) -> None:
    if not name or name in by_name:
        return
    by_name[name] = _AvailableChopScriptRecord(
        name=name,
        executable=str(executable),
        source=source,
        configured=name in configured_scripts,
    )


def _iter_dir(path: Path) -> tuple[Path, ...]:
    try:
        return tuple(path.iterdir())
    except OSError:
        return ()


def _is_executable_file(path: Path) -> bool:
    try:
        return path.is_file() and os.access(path, os.X_OK)
    except OSError:
        return False


def _path_dirs() -> list[str]:
    return [part for part in os.environ.get("PATH", "").split(os.pathsep) if part]
