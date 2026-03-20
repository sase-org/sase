"""YAML config xprompt insertion helpers.

Provides functions to generate and insert xprompt definitions into sase
YAML config files (sase.yml, default_config.yml, etc.) with automatic
alphabetical ordering.
"""

from __future__ import annotations

import re
from pathlib import Path

# Matches an xprompt entry key at exactly 2-space indent (e.g. "  foo:" or
# "  bd/next:").  The captured group is the entry name.
_ENTRY_RE = re.compile(r"^  ([\w/.:-]+):")


def _generate_xprompt_yaml(
    name: str,
    inputs: list[tuple[str, str]],
    content: str,
) -> list[str]:
    """Generate indented YAML lines for a single xprompt entry.

    Returns lines suitable for insertion under a ``xprompts:`` key (2-space
    indent for the entry name, 4-space for its properties).
    """
    content = content.rstrip("\n")

    if not inputs:
        # Short-form:  name: |
        result = [f"  {name}: |"]
        for line in content.split("\n"):
            result.append(f"    {line}" if line.strip() else "")
        return result

    # Long-form with input block
    result = [f"  {name}:"]
    result.append("    input:")
    for arg_name, arg_type in inputs:
        result.append(f"      {arg_name}: {arg_type}")
    result.append("    content: |")
    for line in content.split("\n"):
        result.append(f"      {line}" if line.strip() else "")
    return result


def insert_xprompt_into_config(
    config_path: str,
    name: str,
    inputs: list[tuple[str, str]],
    content: str,
) -> bool:
    """Insert an xprompt definition into a YAML config file.

    The new entry is placed in alphabetical order among existing entries.  If
    the existing entries are not sorted, they are sorted as part of insertion.

    Returns ``True`` on success, ``False`` on failure.
    """
    path = Path(config_path)

    if path.exists():
        file_text = path.read_text(encoding="utf-8")
    else:
        file_text = ""

    lines = file_text.split("\n")

    # Locate the ``xprompts:`` key
    xprompts_idx: int | None = None
    for i, line in enumerate(lines):
        stripped = line.rstrip()
        if stripped == "xprompts:" or stripped == "xprompts: {}":
            xprompts_idx = i
            break

    entry_lines = _generate_xprompt_yaml(name, inputs, content)

    if xprompts_idx is None:
        # No xprompts section — append one at the end of the file.
        while lines and lines[-1].strip() == "":
            lines.pop()
        lines.append("")
        lines.append("xprompts:")
        lines.extend(entry_lines)
        lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")
        return True

    # Replace ``xprompts: {}`` with bare ``xprompts:``
    if lines[xprompts_idx].rstrip() == "xprompts: {}":
        lines[xprompts_idx] = "xprompts:"

    # Determine section boundaries (start = line after key, end = next
    # top-level key or EOF).
    section_start = xprompts_idx + 1
    section_end = len(lines)
    for i in range(section_start, len(lines)):
        line = lines[i]
        if line and not line[0].isspace() and not line.startswith("#"):
            section_end = i
            break

    # Extract each entry as a named block of text lines.
    entry_blocks: dict[str, list[str]] = {}
    current_name: str | None = None
    current_lines: list[str] = []

    for i in range(section_start, section_end):
        line = lines[i]
        m = _ENTRY_RE.match(line)
        if m:
            if current_name is not None:
                while current_lines and current_lines[-1].strip() == "":
                    current_lines.pop()
                entry_blocks[current_name] = current_lines
            current_name = m.group(1)
            current_lines = [line]
        elif current_name is not None:
            current_lines.append(line)

    if current_name is not None:
        while current_lines and current_lines[-1].strip() == "":
            current_lines.pop()
        entry_blocks[current_name] = current_lines

    # Add the new entry and rebuild the section in sorted order.
    entry_blocks[name] = entry_lines
    sorted_names = sorted(entry_blocks.keys())

    new_section: list[str] = []
    for entry_name in sorted_names:
        if new_section:
            new_section.append("")  # blank separator between entries
        new_section.extend(entry_blocks[entry_name])

    # Reconstruct the file.
    result = lines[:section_start] + new_section
    if section_end < len(lines):
        result.append("")  # blank line before next top-level key
        result.extend(lines[section_end:])
    else:
        result.append("")

    path.write_text("\n".join(result), encoding="utf-8")
    return True
