"""Fixed operation catalog for the temporary offline migration kit.

TEMPORARY MODULE: deletion owner sase-x7.14.
"""

from __future__ import annotations

from dataclasses import dataclass

_LEGACY_AGENT_TRIBE_FILENAME = "agent_" + "tags.json"


@dataclass(frozen=True, slots=True)
class OperationSpec:
    """Static metadata for one shipped migration operation."""

    name: str
    title: str
    description: str
    roots: tuple[str, ...]
    owner: str
    backup_required: bool
    apply_supported: bool
    preconditions: tuple[str, ...]
    rollback_unit: str

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "roots": list(self.roots),
            "owner": self.owner,
            "backup_required": self.backup_required,
            "apply_supported": self.apply_supported,
            "preconditions": list(self.preconditions),
            "rollback_unit": self.rollback_unit,
        }


OPERATION_SPECS: tuple[OperationSpec, ...] = (
    OperationSpec(
        name="import-purge",
        title="Purge retired local import state",
        description=(
            "Wraps `sase agent names purge-local-state` behind a verified "
            "backup and re-runs the import-state preview for verification."
        ),
        roots=(
            "~/.sase/agents_sync",
            "~/.sase/artifacts",
            "~/.sase/chats",
            "~/.sase/dismissed_bundles",
            "~/.sase/projects",
        ),
        owner="local-state-cutover",
        backup_required=True,
        apply_supported=True,
        preconditions=(
            "verified backup covers agents_sync, artifacts, chats, dismissed bundles, and projects",
            "local import purge preview can be computed",
        ),
        rollback_unit="verified backup of import-state roots",
    ),
    OperationSpec(
        name="lock-residue",
        title="Classify code-swap lock residue",
        description=(
            "Classifies code-swap lock files and refuses to archive any lock "
            "the current code still writes."
        ),
        roots=("~/.sase/locks",),
        owner="local-state-cutover",
        backup_required=False,
        apply_supported=False,
        preconditions=("read-only classification only",),
        rollback_unit="none; read-only classification",
    ),
    OperationSpec(
        name="procs-residue",
        title="Archive matched legacy proc residue",
        description=(
            "Parses residual ~/.sase/tasks rows, reconciles them with "
            "canonical procs, and archives only a fully matched legacy tree."
        ),
        roots=("~/.sase/tasks", "~/.sase/procs"),
        owner="local-state-cutover",
        backup_required=True,
        apply_supported=True,
        preconditions=(
            "every legacy row has a canonical proc counterpart",
            "no semantic fingerprint conflicts exist",
        ),
        rollback_unit="verified backup plus archived legacy tasks tree",
    ),
    OperationSpec(
        name="state-residue",
        title="Archive declared inert state residue",
        description=(
            "Archives the legacy agent tribe file, user_question, "
            "plan_approval, and legacy ~/.xprompts residue only when "
            "canonical counterparts exist and live records no longer "
            "reference them."
        ),
        roots=(
            f"~/.sase/{_LEGACY_AGENT_TRIBE_FILENAME}",
            "~/.sase/plan_approval",
            "~/.sase/user_question",
            "~/.xprompts",
        ),
        owner="local-state-cutover",
        backup_required=True,
        apply_supported=True,
        preconditions=(
            "declared canonical counterpart exists",
            "no live agent, notification, or gate record references the residue",
        ),
        rollback_unit="verified backup plus per-entry archive copy",
    ),
)


def get_operation_spec(name: str) -> OperationSpec:
    """Return the operation spec named *name* or raise ``KeyError``."""
    return _OPERATION_SPECS_BY_NAME[name]


_OPERATION_SPECS_BY_NAME = {spec.name: spec for spec in OPERATION_SPECS}


__all__ = ["OPERATION_SPECS", "OperationSpec", "get_operation_spec"]
