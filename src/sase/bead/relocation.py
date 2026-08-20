"""Created-bead ID relocation helpers for sync conflict repair."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import tempfile


@dataclass(frozen=True)
class BeadIdRelocation:
    """One bead ID remapped while resolving a semantic bead-store conflict."""

    old_id: str
    new_id: str
    kind: str = "unknown"

    def to_json_dict(self) -> dict[str, str]:
        return {"old_id": self.old_id, "new_id": self.new_id, "kind": self.kind}


def normalize_bead_relocations(payload: Any) -> tuple[BeadIdRelocation, ...]:
    """Return typed relocations from Rust records or legacy pair tuples."""

    records: list[BeadIdRelocation] = []
    if isinstance(payload, Mapping) and payload.get("relocation_records"):
        for record in payload.get("relocation_records") or ():
            if not isinstance(record, Mapping):
                continue
            old_id = str(record.get("old_id") or "")
            new_id = str(record.get("new_id") or "")
            if old_id and new_id:
                records.append(
                    BeadIdRelocation(
                        old_id=old_id,
                        new_id=new_id,
                        kind=str(record.get("kind") or "unknown"),
                    )
                )
        return tuple(records)
    pairs = payload.get("relocations") if isinstance(payload, Mapping) else payload
    for item in pairs or ():
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        old_id = str(item[0] or "")
        new_id = str(item[1] or "")
        if old_id and new_id:
            records.append(BeadIdRelocation(old_id=old_id, new_id=new_id))
    return tuple(records)


def compose_bead_relocations(
    existing: Iterable[BeadIdRelocation],
    new: Iterable[BeadIdRelocation],
) -> tuple[BeadIdRelocation, ...]:
    """Compose relocation chains while preserving direct records."""

    result = list(existing)
    for relocation in new:
        updated: list[BeadIdRelocation] = []
        for current in result:
            if current.new_id == relocation.old_id:
                current = BeadIdRelocation(
                    old_id=current.old_id,
                    new_id=relocation.new_id,
                    kind=current.kind,
                )
            updated.append(current)
        if not any(item.old_id == relocation.old_id for item in updated):
            updated.append(relocation)
        result = updated
    return tuple(result)


def resolve_created_bead_id(
    issue_id: str, relocations: Iterable[BeadIdRelocation] | None
) -> str:
    """Resolve *issue_id* through every known relocation chain."""

    current = issue_id
    seen = {current}
    mapping = {item.old_id: item.new_id for item in relocations or ()}
    while True:
        replacement = mapping.get(current)
        if replacement is None:
            for old_id, new_id in mapping.items():
                prefix = f"{old_id}."
                if current.startswith(prefix):
                    replacement = f"{new_id}.{current[len(prefix) :]}"
                    break
        if replacement is None or replacement in seen:
            return current
        current = replacement
        seen.add(current)


def rewrite_text_for_bead_relocations(
    value: str,
    relocations: Iterable[BeadIdRelocation] | None,
) -> str:
    rewritten = value
    for relocation in relocations or ():
        rewritten = rewritten.replace(relocation.old_id, relocation.new_id)
    return rewritten


def rewrite_head_subject_for_bead_relocations(
    repo_root: Path,
    relocations: Iterable[BeadIdRelocation],
) -> bool:
    """Rewrite the current commit subject if it names a relocated bead id."""

    relocation_tuple = tuple(relocations)
    if not relocation_tuple:
        return False
    from sase.sdd._repository_health import default_git_runner

    result = default_git_runner(
        repo_root,
        ["log", "-1", "--format=%B"],
        op="bead.sync.relocation_subject.read",
    )
    if result.returncode != 0:
        return False
    message = result.stdout or ""
    lines = message.splitlines()
    if not lines:
        return False
    rewritten_subject = rewrite_text_for_bead_relocations(lines[0], relocation_tuple)
    if rewritten_subject == lines[0]:
        return False
    rewritten_message = "\n".join((rewritten_subject, *lines[1:])).rstrip() + "\n"
    from sase.workflows.commit.runtime_tags import (
        apply_auto_commit_type_tag,
        parse_trailing_commit_tag_values,
    )

    if "TYPE" not in parse_trailing_commit_tag_values(rewritten_message):
        rewritten_message = apply_auto_commit_type_tag(rewritten_message, "beads")
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write(rewritten_message)
        message_path = Path(handle.name)
    try:
        amended = default_git_runner(
            repo_root,
            ["commit", "--amend", "-F", str(message_path), "--no-gpg-sign"],
            op="bead.sync.relocation_subject.amend",
        )
        return amended.returncode == 0
    finally:
        try:
            message_path.unlink()
        except OSError:
            pass


__all__ = [
    "BeadIdRelocation",
    "compose_bead_relocations",
    "normalize_bead_relocations",
    "resolve_created_bead_id",
    "rewrite_head_subject_for_bead_relocations",
    "rewrite_text_for_bead_relocations",
]
