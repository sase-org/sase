"""DELTAS persistence — locked read-modify-write helper for ChangeSpec files."""

import logging

from ..changespec import (
    DeltaEntry,
    LockTimeoutError,
    changespec_lock,
    write_changespec_atomic,
)
from ..changespec.deltas_format import format_deltas_field


# Canonical ChangeSpec section order. DELTAS sits between COMMITS and HOOKS;
# any insertion of a missing DELTAS section uses this order to find the slot
# (insert before the first section that comes *after* DELTAS in this list).
CHANGESPEC_SECTION_ORDER: tuple[str, ...] = (
    "NAME:",
    "DESCRIPTION:",
    "PARENT:",
    "CL:",
    "PR:",
    "BUG:",
    "STATUS:",
    "KICKSTART:",
    "TEST TARGETS:",
    "COMMITS:",
    "DELTAS:",
    "HOOKS:",
    "COMMENTS:",
    "MENTORS:",
    "TIMESTAMPS:",
)

_DELTAS_INDEX = CHANGESPEC_SECTION_ORDER.index("DELTAS:")
_POST_DELTAS_HEADERS: tuple[str, ...] = CHANGESPEC_SECTION_ORDER[_DELTAS_INDEX + 1 :]
_ALL_HEADERS: tuple[str, ...] = CHANGESPEC_SECTION_ORDER


def _starts_with_any(line: str, headers: tuple[str, ...]) -> bool:
    return any(line.startswith(h) for h in headers)


def apply_deltas_update(
    lines: list[str],
    changespec_name: str,
    deltas: list[DeltaEntry],
) -> list[str]:
    """Apply DELTAS field update to file lines.

    Behavior:
      - Existing DELTAS section in the target ChangeSpec is replaced.
      - If absent and ``deltas`` is non-empty, a new section is inserted in
        canonical position (before the first post-DELTAS section, i.e. HOOKS;
        or before the next existing section if HOOKS is absent).
      - If ``deltas`` is empty, any existing DELTAS section is removed; nothing
        is inserted.
    """
    formatted = format_deltas_field(deltas)

    updated: list[str] = []
    in_target = False
    found_deltas = False
    inserted = False
    i = 0

    while i < len(lines):
        line = lines[i]

        if line.startswith("NAME:"):
            current = line.split(":", 1)[1].strip()
            was_in_target = in_target
            in_target = current == changespec_name

            # Leaving the target ChangeSpec without finding DELTAS — insert
            # before this NAME line if we still owe an insertion.
            if was_in_target and not found_deltas and formatted and not inserted:
                updated.extend(formatted)
                inserted = True

            updated.append(line)
            i += 1
            continue

        # Existing DELTAS section: skip its body, optionally writing the new one.
        if in_target and line.startswith("DELTAS:"):
            found_deltas = True
            if formatted and not inserted:
                updated.extend(formatted)
                inserted = True
            i += 1
            while i < len(lines):
                next_line = lines[i]
                if _starts_with_any(next_line, _ALL_HEADERS):
                    break
                if (
                    next_line.strip() == ""
                    and i + 1 < len(lines)
                    and lines[i + 1].strip() == ""
                ):
                    break
                i += 1
            continue

        # Insertion point: the first post-DELTAS section header in target CS.
        if (
            in_target
            and not found_deltas
            and formatted
            and not inserted
            and _starts_with_any(line, _POST_DELTAS_HEADERS)
        ):
            updated.extend(formatted)
            inserted = True

        # Insertion point: end-of-ChangeSpec via two consecutive blank lines.
        if (
            in_target
            and not found_deltas
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

    # End of file while still in target ChangeSpec.
    if in_target and not found_deltas and formatted and not inserted:
        updated.extend(formatted)

    return updated


def update_changespec_deltas_field(
    project_file: str,
    changespec_name: str,
    deltas: list[DeltaEntry],
) -> bool:
    """Locked read-modify-write of the DELTAS field for a ChangeSpec.

    Args:
        project_file: Path to the ProjectSpec ``.gp`` file.
        changespec_name: NAME of the ChangeSpec to update.
        deltas: DeltaEntry list to write. Empty list removes the section.

    Returns:
        True on success, False on lock timeout or write failure.
    """
    try:
        with changespec_lock(project_file):
            with open(project_file, encoding="utf-8") as f:
                lines = f.readlines()
            updated = apply_deltas_update(lines, changespec_name, deltas)
            write_changespec_atomic(
                project_file,
                "".join(updated),
                f"Update DELTAS for {changespec_name}",
            )
            return True
    except LockTimeoutError:
        logging.warning(
            f"Lock timeout updating deltas for {changespec_name} in {project_file}"
        )
        return False
    except Exception as e:
        logging.error(f"Failed to update deltas for {changespec_name}: {e}")
        return False
