"""REFS persistence — locked read-modify-write helpers for ChangeSpec files."""

from __future__ import annotations

import logging

from sase.artifact_ref_lists import normalize_artifact_ref_list

from .locking import (
    LockTimeoutError,
    changespec_lock,
    write_changespec_atomic,
)
from .refs_format import format_refs_field
from .section_order import PATCH_SECTION_ORDER, PROJECT_SPEC_SECTION_HEADERS


_REFS_INDEX = PATCH_SECTION_ORDER.index("REFS:")
_POST_REFS_HEADERS = PATCH_SECTION_ORDER[_REFS_INDEX + 1 :]


def _starts_with_any(line: str, headers: tuple[str, ...]) -> bool:
    return line.startswith(headers)


def apply_refs_update(
    lines: list[str],
    changespec_name: str,
    refs: list[str] | tuple[str, ...],
) -> list[str]:
    """Replace, insert, or remove one ChangeSpec's normalized REFS section."""

    normalized = normalize_artifact_ref_list(refs)
    formatted = format_refs_field(normalized)
    updated: list[str] = []
    in_target = False
    found_refs = False
    inserted = False
    i = 0

    while i < len(lines):
        line = lines[i]

        if line.startswith("NAME:"):
            current = line.split(":", 1)[1].strip()
            was_in_target = in_target
            in_target = current == changespec_name
            if was_in_target and not found_refs and formatted and not inserted:
                updated.extend(formatted)
                inserted = True
            updated.append(line)
            i += 1
            continue

        if in_target and line.startswith("REFS:"):
            found_refs = True
            if formatted and not inserted:
                updated.extend(formatted)
                inserted = True
            i += 1
            while i < len(lines):
                next_line = lines[i]
                if _starts_with_any(next_line, PROJECT_SPEC_SECTION_HEADERS):
                    break
                if (
                    next_line.strip() == ""
                    and i + 1 < len(lines)
                    and lines[i + 1].strip() == ""
                ):
                    break
                i += 1
            continue

        if (
            in_target
            and not found_refs
            and formatted
            and not inserted
            and _starts_with_any(line, _POST_REFS_HEADERS)
        ):
            updated.extend(formatted)
            inserted = True

        if (
            in_target
            and not found_refs
            and formatted
            and not inserted
            and line.strip() == ""
            and i + 1 < len(lines)
            and lines[i + 1].strip() == ""
        ):
            updated.extend(formatted)
            inserted = True

        updated.append(line)
        i += 1

    if in_target and not found_refs and formatted and not inserted:
        updated.extend(formatted)

    return updated


def update_changespec_refs_field(
    project_file: str,
    changespec_name: str,
    refs: list[str] | tuple[str, ...],
) -> bool:
    """Atomically normalize and persist one ChangeSpec's references."""

    try:
        with changespec_lock(project_file):
            with open(project_file, encoding="utf-8") as stream:
                lines = stream.readlines()
            updated = apply_refs_update(lines, changespec_name, refs)
            if updated == lines:
                return True
            write_changespec_atomic(
                project_file,
                "".join(updated),
                f"Update REFS for {changespec_name}",
            )
            return True
    except LockTimeoutError:
        logging.warning(
            "Lock timeout updating refs for %s in %s",
            changespec_name,
            project_file,
        )
        return False
    except Exception:
        logging.exception("Failed to update refs for %s", changespec_name)
        return False


update_patch_refs_field = update_changespec_refs_field
_apply_refs_update = apply_refs_update


__all__ = [
    "apply_refs_update",
    "update_changespec_refs_field",
    "update_patch_refs_field",
]
