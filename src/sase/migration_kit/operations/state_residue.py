"""Declared inert state-residue operation.

TEMPORARY MODULE: deletion owner sase-x7.14.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.migration_kit.catalog import get_operation_spec
from sase.migration_kit.core_contract import classify_residue
from sase.migration_kit.operations.base import OperationContext, OperationOutcome
from sase.migration_kit.operations.util import (
    archive_remove_actions,
    digest_path,
    find_symlink_escapes,
    fingerprint_json,
    live_references,
)

_LEGACY_AGENT_TRIBE_FILENAME = "agent_" + "tags.json"


@dataclass(frozen=True, slots=True)
class _ResidueEntry:
    entry_id: str
    residue_kind: str
    canonical_counterpart: str
    relative_to: str

    def residue_path(self, context: OperationContext) -> Path:
        root = context.home if self.relative_to == "home" else context.sase_home
        return root / self.residue_kind

    def counterpart_path(self, context: OperationContext) -> Path:
        root = context.home if self.relative_to == "home" else context.sase_home
        return root / self.canonical_counterpart


_RESIDUE_ENTRIES: tuple[_ResidueEntry, ...] = (
    _ResidueEntry(
        entry_id="agent-tags",
        residue_kind=_LEGACY_AGENT_TRIBE_FILENAME,
        canonical_counterpart="agent_tribes.json",
        relative_to="sase_home",
    ),
    _ResidueEntry(
        entry_id="plan-approval",
        residue_kind="plan_approval",
        canonical_counterpart="notifications/notifications.jsonl",
        relative_to="sase_home",
    ),
    _ResidueEntry(
        entry_id="user-question",
        residue_kind="user_question",
        canonical_counterpart="notifications/notifications.jsonl",
        relative_to="sase_home",
    ),
    _ResidueEntry(
        entry_id="xprompts",
        residue_kind=".xprompts",
        canonical_counterpart=".sase/config.yml",
        relative_to="home",
    ),
)


class StateResidueOperation:
    """Archive only declared inert state residue."""

    spec = get_operation_spec("state-residue")

    def plan(self, context: OperationContext) -> dict[str, Any]:
        classifications: list[dict[str, Any]] = []
        actions: list[dict[str, Any]] = []
        conflicts: list[dict[str, Any]] = []
        source_digests: dict[str, str] = {}
        record_counts: dict[str, int] = {}
        semantic_records: list[dict[str, Any]] = []
        estimated_space = 0

        for entry in _RESIDUE_ENTRIES:
            residue = entry.residue_path(context)
            counterpart = entry.counterpart_path(context)
            residue_label = str(residue)
            counterpart_label = str(counterpart)
            source_digests[residue_label] = digest_path(residue)
            exists = residue.exists() or residue.is_symlink()
            if exists and residue.is_file():
                estimated_space += residue.stat().st_size
            elif exists and residue.is_dir():
                estimated_space += sum(
                    child.stat().st_size
                    for child in residue.rglob("*")
                    if child.is_file() and not child.is_symlink()
                )

            references = live_references(
                sase_home=context.sase_home,
                needles=(residue_label, residue.as_posix(), entry.residue_kind),
            )
            facts = {
                "schema_version": 1,
                "residue_exists": exists,
                "counterpart_exists": counterpart.exists() or counterpart.is_symlink(),
                "live_references": list(references),
                "archived": False,
            }
            wire_entry = {
                "schema_version": 1,
                "entry_id": entry.entry_id,
                "residue_path": residue_label,
                "canonical_counterpart": counterpart_label,
                "precondition_query": {
                    "counterpart": counterpart_label,
                    "live_reference_scan": [
                        "notifications",
                        "pending_actions",
                        "gates",
                        "gate_shells",
                        "procs",
                    ],
                },
            }
            classification = classify_residue(wire_entry, facts)
            classifications.append(classification)
            semantic_records.append(classification)
            if classification["decision"] == "archive":
                escapes = find_symlink_escapes(context.home, residue)
                if escapes:
                    conflicts.append(
                        _conflict(
                            path=residue_label,
                            kind="symlink_escape",
                            detail="; ".join(escapes),
                        )
                    )
                    continue
                source_digest = source_digests[residue_label]
                actions.append(
                    {
                        "action_id": entry.entry_id,
                        "kind": "archive_remove",
                        "source": residue_label,
                        "source_digest": source_digest,
                        "canonical_counterpart": counterpart_label,
                    }
                )
                record_counts[entry.entry_id] = 1
            elif str(classification["decision"]).startswith("refuse_"):
                conflicts.append(
                    _conflict(
                        path=residue_label,
                        kind=str(classification["decision"]),
                        detail=str(classification["reason"]),
                    )
                )
                record_counts[entry.entry_id] = 1 if exists else 0
            else:
                record_counts[entry.entry_id] = 0

        return {
            "schema_version": 1,
            "operation": self.spec.name,
            "roots": [str(context.sase_home), str(context.home / ".xprompts")],
            "source_paths": sorted(source_digests),
            "destinations": [],
            "source_digests": source_digests,
            "schema_versions": {"migration": 1},
            "record_counts": record_counts,
            "semantic_fingerprints": {
                "state-residue": fingerprint_json(semantic_records)
            },
            "detected_conflicts": conflicts,
            "estimated_space_bytes": estimated_space,
            "backup_required": self.spec.backup_required,
            "backup_ids": [context.backup_id] if context.backup_id else [],
            "preconditions": list(self.spec.preconditions),
            "verification_query": {
                "classifications": classifications,
                "residue_entries": [entry.entry_id for entry in _RESIDUE_ENTRIES],
            },
            "rollback_unit": self.spec.rollback_unit,
            "intended_action": "dry_run",
            "x_actions": actions,
            "x_classifications": classifications,
        }

    def apply(
        self, context: OperationContext, operation_entry: dict[str, Any]
    ) -> OperationOutcome:
        return archive_remove_actions(
            context=context,
            operation=self.spec.name,
            operation_entry=operation_entry,
        )

    def verify(
        self, context: OperationContext, operation_entry: dict[str, Any]
    ) -> OperationOutcome:
        failures: list[str] = []
        for action in operation_entry.get("x_actions", []):
            if not isinstance(action, dict):
                continue
            source = Path(str(action["source"]))
            if source.exists() or source.is_symlink():
                failures.append(f"{source}: residue still exists")
        return OperationOutcome(
            not failures,
            "state residue post-conditions verified"
            if not failures
            else "state residue remains after apply",
            errors=tuple(failures),
        )


def _conflict(*, path: str, kind: str, detail: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "path": path,
        "kind": kind,
        "detail": detail,
    }


__all__ = ["StateResidueOperation"]
