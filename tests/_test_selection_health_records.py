"""Typed views over the records :mod:`tests._test_selection_health_store` writes.

Both record kinds are JSON written by an earlier run — possibly by an earlier
*version* — so everything here reads defensively: unparseable files are
skipped, and every field is projected through a property that copes with the
key being absent. The two ``identity`` properties are the load-bearing ones:
they return ``None`` for a record that carries no workspace or change set,
which is how pre-schema-2 records stay out of the correlation in
:mod:`tests._test_selection_health`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tests._test_selection_health_store import KIND_FULL_RUN, KIND_SELECTION


@dataclass(frozen=True)
class SelectionRecord:
    name: str
    recorded_at: str | None
    manifest: dict[str, Any]
    workspace: str | None = None

    @property
    def changed_files(self) -> frozenset[str] | None:
        """The change set this run selected for, or ``None`` if unrecorded."""
        changed = self.manifest.get("changed_files")
        if not isinstance(changed, list):
            return None
        return frozenset(str(path) for path in changed)

    @property
    def identity(self) -> tuple[str, frozenset[str]] | None:
        """Workspace and change set, or ``None`` when either is missing."""
        changed = self.changed_files
        if self.workspace is None or changed is None:
            return None
        return (self.workspace, changed)

    @property
    def head(self) -> str | None:
        head = (self.manifest.get("baseline") or {}).get("head")
        return str(head) if head else None

    @property
    def escalated(self) -> bool:
        return bool(self.manifest.get("escalated"))

    @property
    def selected(self) -> frozenset[str]:
        return frozenset(str(path) for path in self.manifest.get("selected") or ())

    @property
    def selected_count(self) -> int:
        return int(self.manifest.get("selected_count") or 0)

    @property
    def rules(self) -> tuple[str, ...]:
        return tuple(str(rule) for rule in self.manifest.get("rules_fired") or ())

    @property
    def duration(self) -> float | None:
        duration = self.manifest.get("duration")
        return float(duration) if isinstance(duration, (int, float)) else None

    @property
    def outcome(self) -> str:
        return str(self.manifest.get("outcome") or "unknown")

    @property
    def contexts(self) -> dict[str, Any]:
        contexts = self.manifest.get("contexts")
        return contexts if isinstance(contexts, dict) else {}


@dataclass(frozen=True)
class FullRunRecord:
    name: str
    recorded_at: str | None
    head: str | None
    mode: str
    failures: tuple[str, ...]
    workspace: str | None = None
    changed_files: frozenset[str] | None = None

    @property
    def identity(self) -> tuple[str, frozenset[str]] | None:
        """Workspace and change set, or ``None`` when either is missing."""
        if self.workspace is None or self.changed_files is None:
            return None
        return (self.workspace, self.changed_files)


@dataclass(frozen=True)
class HealthRecords:
    selections: tuple[SelectionRecord, ...] = ()
    full_runs: tuple[FullRunRecord, ...] = ()


def load_records(store: Path) -> HealthRecords:
    """Read every readable record in ``store``; ignore anything unparseable."""
    selections: list[SelectionRecord] = []
    full_runs: list[FullRunRecord] = []
    try:
        entries = sorted(store.glob("*.json"))
    except OSError:
        entries = []
    for entry in entries:
        try:
            payload = json.loads(entry.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        recorded_at = payload.get("recorded_at")
        recorded_at = str(recorded_at) if recorded_at else None
        workspace = payload.get("workspace")
        workspace = str(workspace) if workspace else None
        kind = payload.get("kind")
        if kind == KIND_SELECTION and isinstance(payload.get("manifest"), dict):
            selections.append(
                SelectionRecord(
                    name=entry.name,
                    recorded_at=recorded_at,
                    manifest=payload["manifest"],
                    workspace=workspace,
                )
            )
        elif kind == KIND_FULL_RUN:
            head = payload.get("head")
            changed = payload.get("changed_files")
            full_runs.append(
                FullRunRecord(
                    name=entry.name,
                    recorded_at=recorded_at,
                    head=str(head) if head else None,
                    mode=str(payload.get("mode") or "unknown"),
                    failures=tuple(
                        str(failure) for failure in payload.get("failures") or ()
                    ),
                    workspace=workspace,
                    changed_files=(
                        frozenset(str(path) for path in changed)
                        if isinstance(changed, list)
                        else None
                    ),
                )
            )
    return HealthRecords(selections=tuple(selections), full_runs=tuple(full_runs))
