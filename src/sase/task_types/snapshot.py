"""Committed catalog snapshot assembly (D6) for ``sase memory init``.

The snapshot is the deterministic, git-committed render source for the
generated task-type memory note: every catalog member, keyed by the same
digest ``sase bead task-type show`` already reports, so a project's committed
configuration -- not whichever plugins happen to be installed locally --
decides what the note documents.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from typing import Any

from sase.core.rust import require_rust_binding
from sase.version._utils import normalize_distribution_name

from ._models import TaskTypeRecord, TaskTypeRegistry


def task_type_snapshot_entry(record: TaskTypeRecord) -> dict[str, Any]:
    """Return one ``TaskTypeSnapshotEntryWire``-shaped dict for *record*."""

    spec = record.spec
    return {
        "task_type": record.task_type,
        "label": spec.get("label", record.task_type),
        "summary": spec.get("summary", ""),
        "when_to_use": spec.get("when_to_use", ""),
        "glyph": spec.get("glyph"),
        "accent_color": spec.get("accent_color"),
        "agent_creatable": record.agent_creatable,
        "default_size": spec.get("default_size"),
        "fields": [dict(field) for field in spec.get("fields", ())],
        "body_template": spec.get("body_template"),
        "triage": dict(spec.get("triage") or {"min_plus_ones": 0}),
        "source": record.provenance.source,
        "package": record.provenance.package,
        "digest": record.digest,
    }


def build_task_type_snapshot_entries(
    registry: TaskTypeRegistry,
) -> tuple[dict[str, Any], ...]:
    """Return every registry record as a sorted snapshot entry."""

    return _snapshot_entries_for(registry.records)


def committed_task_type_records(
    registry: TaskTypeRegistry,
    *,
    required_packages: frozenset[str] | None = None,
) -> tuple[TaskTypeRecord, ...]:
    """Return the catalog members that belong in ``sase/task_types.json``.

    Builtins and project-config types always belong. A plugin type belongs only
    when its distribution is listed in ``plugins.required``, so two machines
    with different optional plugin sets write the same snapshot and the same
    generated instruction files.
    """

    packages = (
        required_packages
        if required_packages is not None
        else _project_required_plugin_packages()
    )
    return tuple(
        record
        for record in registry.records
        if _record_belongs_in_committed_snapshot(record, packages)
    )


def build_committed_task_type_snapshot_entries(
    registry: TaskTypeRegistry,
    *,
    required_packages: frozenset[str] | None = None,
) -> tuple[dict[str, Any], ...]:
    """Return snapshot entries for the committed catalog only."""

    return _snapshot_entries_for(
        committed_task_type_records(registry, required_packages=required_packages)
    )


def render_task_type_snapshot_json(entries: Sequence[Mapping[str, Any]]) -> str:
    """Serialize *entries* through the deterministic Rust snapshot codec."""

    payload = {"types": [dict(entry) for entry in entries]}
    return str(require_rust_binding("serialize_task_type_snapshot")(payload))


def describe_task_type_snapshot_drift(
    committed_json: str,
    live_json: str,
    *,
    registry: TaskTypeRegistry | None = None,
) -> str:
    """Name digest or membership changes between two snapshot documents.

    Returns an empty string when the snapshots cannot be parsed or when they
    already agree, so callers can fall back to a generic file-level detail.
    """

    committed = _snapshot_types_by_slug(committed_json)
    live = _snapshot_types_by_slug(live_json)
    if committed is None or live is None:
        return ""
    records = {} if registry is None else dict(registry.by_slug)
    messages: list[str] = []
    for slug in sorted(set(committed) | set(live)):
        old = committed.get(slug)
        new = live.get(slug)
        if old is None:
            messages.append(
                f"`{slug}` is not in the committed snapshot "
                f"({_installed_package_clause(slug, new, records)}); "
                "run `sase memory init`"
            )
            continue
        if new is None:
            messages.append(
                f"`{slug}` is in the committed snapshot but not in the live catalog"
            )
            continue
        if old.get("digest") != new.get("digest"):
            messages.append(
                f"`{slug}` spec digest changed "
                f"({_installed_package_clause(slug, new, records)}); "
                "run `sase memory init`"
            )
    return "; ".join(messages)


def _snapshot_entries_for(
    records: Sequence[TaskTypeRecord],
) -> tuple[dict[str, Any], ...]:
    entries = [task_type_snapshot_entry(record) for record in records]
    entries.sort(key=lambda entry: str(entry["task_type"]))
    return tuple(entries)


def _record_belongs_in_committed_snapshot(
    record: TaskTypeRecord,
    required_packages: frozenset[str],
) -> bool:
    if record.provenance.source in {"builtin", "project"}:
        return True
    package = normalize_distribution_name(record.provenance.package)
    return bool(package) and package in required_packages


def _project_required_plugin_packages() -> frozenset[str]:
    from sase.content_layout import discover_project_root
    from sase.plugins.required import (
        load_project_required_plugins_config,
        required_plugin_distribution_names,
    )

    root = discover_project_root()
    if root is None:
        return frozenset()
    config, _path, error = load_project_required_plugins_config(root)
    if error is not None or config is None:
        return frozenset()
    return required_plugin_distribution_names(config)


def _snapshot_types_by_slug(raw: str) -> dict[str, Mapping[str, Any]] | None:
    """Parse snapshot JSON without re-validating digests.

    ``--check`` must still name a digest change after a committed file is
    edited, so this path cannot go through the Rust snapshot validator.
    """
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, Mapping):
        return None
    types = parsed.get("types")
    if not isinstance(types, list):
        return None
    by_slug: dict[str, Mapping[str, Any]] = {}
    for entry in types:
        if not isinstance(entry, Mapping):
            continue
        slug = str(entry.get("task_type") or "")
        if slug:
            by_slug[slug] = entry
    return by_slug


def _installed_package_clause(
    slug: str,
    entry: Mapping[str, Any] | None,
    records: Mapping[str, TaskTypeRecord],
) -> str:
    record = records.get(slug)
    package = ""
    version = ""
    if record is not None:
        package = record.provenance.package
        version = record.provenance.version
    elif entry is not None:
        package = str(entry.get("package") or "")
    package = package or "unknown"
    if version and version != "<unknown>":
        return f"{package} {version} installed"
    return f"{package} installed"


__all__ = [
    "build_committed_task_type_snapshot_entries",
    "build_task_type_snapshot_entries",
    "committed_task_type_records",
    "describe_task_type_snapshot_drift",
    "render_task_type_snapshot_json",
    "task_type_snapshot_entry",
]
