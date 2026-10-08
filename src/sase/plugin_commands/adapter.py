"""Adapter loading for one mounted plugin command.

Resolves the ``module`` (or ``module:object``) entry-point value to the
duck-typed adapter, checks the contract version and required members, and
resolves the display summary. Failures raise
:class:`PluginCommandLoadError`, which carries the distribution, version, and
cause so dispatch can print a repair line. Exceptions raised by the plugin's
own ``main`` are never wrapped here.
"""

from __future__ import annotations

import importlib
import importlib.metadata
from dataclasses import dataclass
from typing import Any

from sase.plugin_commands.scan import PluginCommandRecord

#: Contract version this sase understands. Absent ``SASE_COMMAND_API`` means 1.
SUPPORTED_COMMAND_API = 1


class PluginCommandLoadError(Exception):
    """A mounted plugin command's adapter could not be loaded."""

    def __init__(
        self, *, command: str, distribution: str, version: str, cause: str
    ) -> None:
        super().__init__(cause)
        self.command = command
        self.distribution = distribution
        self.version = version
        self.cause = cause


@dataclass(frozen=True)
class LoadedPluginCommand:
    """One loaded command adapter with its resolved summary."""

    record: PluginCommandRecord
    main: Any
    build_parser: Any
    summary: str
    api_version: int


def load_plugin_command(record: PluginCommandRecord) -> LoadedPluginCommand:
    """Load one mounted command's adapter or raise :class:`PluginCommandLoadError`."""
    target = _load_adapter_target(record)
    api_version = _check_api_version(record, target)
    main = _require_callable(record, target, "main")
    build_parser = _require_callable(record, target, "build_parser")
    return LoadedPluginCommand(
        record=record,
        main=main,
        build_parser=build_parser,
        summary=resolve_command_summary(record, target),
        api_version=api_version,
    )


def resolve_command_summary(
    record: PluginCommandRecord, target: Any | None = None
) -> str:
    """Return the display summary for *record*, preferring ``SUMMARY``."""
    if target is None:
        try:
            target = _load_adapter_target(record)
        except PluginCommandLoadError:
            target = None
    if target is not None:
        summary = getattr(target, "SUMMARY", None)
        if isinstance(summary, str) and summary.strip():
            return summary.strip()
    return _distribution_summary(record.distribution)


def _load_adapter_target(record: PluginCommandRecord) -> Any:
    try:
        module_name, attribute = _split_value(record.value)
    except ValueError as exc:
        raise PluginCommandLoadError(
            command=record.name,
            distribution=record.distribution,
            version=record.version,
            cause=str(exc),
        ) from exc
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        raise PluginCommandLoadError(
            command=record.name,
            distribution=record.distribution,
            version=record.version,
            cause=f"could not import {module_name!r}: {exc}",
        ) from exc
    target: Any = module
    if attribute is not None:
        try:
            for part in attribute.split("."):
                target = getattr(target, part)
        except AttributeError as exc:
            raise PluginCommandLoadError(
                command=record.name,
                distribution=record.distribution,
                version=record.version,
                cause=f"could not resolve {record.value!r}: {exc}",
            ) from exc
    return target


def _split_value(value: str) -> tuple[str, str | None]:
    """Split an entry-point value into ``(module, attribute)``."""
    cleaned = value.split("[", 1)[0].strip()
    if not cleaned:
        raise ValueError("entry point value is empty")
    module_name, separator, attribute = cleaned.partition(":")
    module_name = module_name.strip()
    if not module_name:
        raise ValueError(f"entry point value {value!r} names no module")
    if not separator:
        return module_name, None
    attribute = attribute.strip()
    if not attribute:
        raise ValueError(f"entry point value {value!r} names no object")
    return module_name, attribute


def _check_api_version(record: PluginCommandRecord, target: Any) -> int:
    api_version = getattr(target, "SASE_COMMAND_API", 1)
    if isinstance(api_version, bool) or not isinstance(api_version, int):
        raise PluginCommandLoadError(
            command=record.name,
            distribution=record.distribution,
            version=record.version,
            cause="SASE_COMMAND_API must be an int",
        )
    if api_version > SUPPORTED_COMMAND_API:
        raise PluginCommandLoadError(
            command=record.name,
            distribution=record.distribution,
            version=record.version,
            cause=f"requires a newer sase (SASE_COMMAND_API={api_version}) — run `sase update`",
        )
    if api_version < 1:
        raise PluginCommandLoadError(
            command=record.name,
            distribution=record.distribution,
            version=record.version,
            cause=f"unsupported SASE_COMMAND_API={api_version}",
        )
    return api_version


def _require_callable(record: PluginCommandRecord, target: Any, member: str) -> Any:
    candidate = getattr(target, member, None)
    if not callable(candidate):
        raise PluginCommandLoadError(
            command=record.name,
            distribution=record.distribution,
            version=record.version,
            cause=f"adapter {record.value!r} has no callable {member!r}",
        )
    return candidate


def _distribution_summary(distribution: str) -> str:
    try:
        metadata = importlib.metadata.metadata(distribution)
    except Exception:
        return ""
    summary = metadata.get("Summary", "")
    return summary.strip() if isinstance(summary, str) else ""
