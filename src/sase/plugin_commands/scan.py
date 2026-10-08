"""Metadata-only discovery for plugin-mounted top-level commands.

Walks ``importlib.metadata.distributions()`` and keeps each distribution's
own ``sase_commands`` entry points, without importing anything, so unknown
root words pay a small metadata scan instead of a full argparse build, and
warm ``completion ensure`` callers can use this module without importing
``sase.main.parser*`` (see ``tests/main/test_completion_ensure_contract.py``).

The per-distribution walk is deliberate: the ``entry_points(group=...)``
selector collapses same-named entry points across distributions to one, which
would hide duplicate owners. Conflict detection needs every claimant.

This module imports only the standard library. Keep it that way.
"""

from __future__ import annotations

import importlib.metadata
import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass

#: Entry-point group a distribution uses to mount top-level commands.
COMMANDS_ENTRY_POINT_GROUP = "sase_commands"

#: Per-group disable switch for plugin commands (plus ``SASE_DISABLE_PLUGINS``).
COMMANDS_DISABLE_ENV_VAR = "SASE_DISABLE_PLUGIN_COMMANDS"

#: Global switch that disables every plugin group, including commands.
PLUGINS_DISABLE_ENV_VAR = "SASE_DISABLE_PLUGINS"


@dataclass(frozen=True)
class PluginCommandRecord:
    """One declared ``sase_commands`` entry point, metadata only."""

    name: str
    value: str
    distribution: str
    version: str
    location: str
    editable: bool


def disabling_env_var() -> str | None:
    """Return the disable switch currently turning plugin commands off, if any."""
    if os.environ.get(PLUGINS_DISABLE_ENV_VAR):
        return PLUGINS_DISABLE_ENV_VAR
    if os.environ.get(COMMANDS_DISABLE_ENV_VAR):
        return COMMANDS_DISABLE_ENV_VAR
    return None


def commands_disabled() -> bool:
    """Return whether plugin commands are disabled via environment switches."""
    return disabling_env_var() is not None


def scan_plugin_commands(
    *, honor_disable: bool = True
) -> tuple[PluginCommandRecord, ...]:
    """Return sorted ``sase_commands`` records without importing anything.

    With ``honor_disable`` (used for dispatch and help), an active disable
    switch yields no records. With ``honor_disable=False`` (used for
    lifecycle diffs and cache identity), every declared record is returned
    regardless of the switches.
    """
    if honor_disable and commands_disabled():
        return ()
    records = [_record_from_entry_point(ep) for ep in _entry_points()]
    records.sort(
        key=lambda record: (
            record.name.casefold(),
            record.distribution.casefold(),
            record.value,
        )
    )
    return tuple(records)


def _entry_points() -> list[importlib.metadata.EntryPoint]:
    found: list[importlib.metadata.EntryPoint] = []
    for dist in importlib.metadata.distributions():
        try:
            points = dist.entry_points
        except Exception:
            continue
        for ep in points:
            if ep.group == COMMANDS_ENTRY_POINT_GROUP:
                found.append(ep)
    return sorted(found, key=lambda ep: ep.name)


def _record_from_entry_point(ep: importlib.metadata.EntryPoint) -> PluginCommandRecord:
    distribution = _entry_point_distribution(ep)
    version = _entry_point_version(ep)
    location, editable = _entry_point_location(ep)
    name = ep.name if isinstance(ep.name, str) else ""
    value = ep.value if isinstance(ep.value, str) else ""
    return PluginCommandRecord(
        name=name,
        value=value,
        distribution=distribution,
        version=version,
        location=location,
        editable=editable,
    )


def _entry_point_distribution(ep: importlib.metadata.EntryPoint) -> str:
    dist = getattr(ep, "dist", None)
    metadata = getattr(dist, "metadata", None)
    getter = getattr(metadata, "get", None)
    if callable(getter):
        try:
            name = getter("Name")
        except Exception:
            name = None
        if isinstance(name, str) and name:
            return name
    direct_name = getattr(dist, "name", None)
    if isinstance(direct_name, str) and direct_name:
        return direct_name
    return "<unknown>"


def _entry_point_version(ep: importlib.metadata.EntryPoint) -> str:
    dist = getattr(ep, "dist", None)
    version = getattr(dist, "version", None)
    if isinstance(version, str) and version:
        return version
    metadata = getattr(dist, "metadata", None)
    getter = getattr(metadata, "get", None)
    if callable(getter):
        try:
            metadata_version = getter("Version")
        except Exception:
            metadata_version = None
        if isinstance(metadata_version, str) and metadata_version:
            return metadata_version
    return "<unknown>"


def _entry_point_location(ep: importlib.metadata.EntryPoint) -> tuple[str, bool]:
    """Return ``(location, editable)`` for one entry point's distribution.

    The location is the ``.dist-info`` directory, except for editable
    installs, where it is the source root read from ``direct_url.json``.
    """
    dist_info = _dist_info_path(ep)
    source_root = _editable_source_root(dist_info)
    if source_root is not None:
        return source_root, True
    return dist_info, False


def _dist_info_path(ep: importlib.metadata.EntryPoint) -> str:
    dist = getattr(ep, "dist", None)
    raw_path = getattr(dist, "_path", None)
    if raw_path is not None:
        try:
            return os.fspath(raw_path)
        except TypeError:
            pass
    locate_file = getattr(dist, "locate_file", None)
    if callable(locate_file):
        try:
            return os.fspath(locate_file(""))
        except Exception:
            pass
    return ""


def _editable_source_root(dist_info: str) -> str | None:
    """Return the editable source root when *dist_info* declares one."""
    if not dist_info:
        return None
    try:
        with open(
            os.path.join(dist_info, "direct_url.json"), encoding="utf-8"
        ) as handle:
            direct_url = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(direct_url, dict):
        return None
    dir_info = direct_url.get("dir_info")
    if not isinstance(dir_info, dict) or dir_info.get("editable") is not True:
        return None
    url = direct_url.get("url")
    if not isinstance(url, str) or not url:
        return None
    return _file_url_to_path(url)


def _file_url_to_path(url: str) -> str | None:
    """Return the local path for a ``file:`` URL, or ``None`` when remote."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "file":
        return None
    path = urllib.request.url2pathname(urllib.parse.unquote(parsed.path))
    if os.name == "nt" and path.startswith("/") and len(path) > 2 and path[2] == ":":
        path = path[1:]
    return path or None
