"""Cross-linking helpers for multi-step agent chat history files.

Builds markdown link tables connecting planner, feedback, and coder chat
files, and formats plan-file previews as synthetic responses for
intermediate steps.
"""

import re


def build_linked_chats_section(
    links: list[tuple[str, str]],
    current_role: str | None = None,
) -> str:
    """Build a ``## Linked Chats`` markdown table.

    Args:
        links: List of ``(role_suffix, chat_path)`` pairs.
        current_role: If given, bold the matching row.

    Returns:
        A markdown section string including the heading and table.
    """
    lines = [
        "## Linked Chats",
        "",
        "| Step | Role | Chat |",
        "|------|------|------|",
    ]
    for step, (role, path) in enumerate(links, 1):
        if current_role is not None and role == current_role:
            lines.append(f"| **{step}** | **{role}** | **`{path}`** |")
        else:
            lines.append(f"| {step} | {role} | `{path}` |")
    return "\n".join(lines) + "\n"


def append_links_to_chat(chat_path: str, links_section: str) -> None:
    """Insert or replace a ``## Linked Chats`` section in *chat_path*.

    The section is placed immediately after the ``**Timestamp:**`` line
    (and any blank line following it), before the remaining content.
    If a ``## Linked Chats`` section already exists it is replaced.
    """
    try:
        with open(chat_path, encoding="utf-8") as f:
            content = f.read()
    except (FileNotFoundError, OSError):
        return

    # Strip any existing linked-chats section
    content = re.sub(
        r"## Linked Chats\n(?:.*\n)*?(?=\n## |\Z)",
        "",
        content,
    )

    # Find the insertion point: after the **Timestamp:** line
    m = re.search(r"(\*\*Timestamp:\*\*[^\n]*\n\n?)", content)
    if m:
        insert_at = m.end()
        content = (
            content[:insert_at] + "\n" + links_section + "\n" + content[insert_at:]
        )
    else:
        # Fallback: prepend to content
        content = links_section + "\n" + content

    with open(chat_path, "w", encoding="utf-8") as f:
        f.write(content)


def format_plan_as_response(plan_file: str, max_preview_lines: int = 10) -> str:
    """Format a plan file as a synthetic chat response.

    Reads the plan, extracts the first *max_preview_lines* non-empty
    content lines (skipping YAML frontmatter), and returns a short
    markdown summary suitable for the ``## Response`` section.

    Args:
        plan_file: Path to the plan markdown file.
        max_preview_lines: Maximum number of preview lines to include.

    Returns:
        Formatted markdown string.
    """
    try:
        with open(plan_file, encoding="utf-8") as f:
            raw = f.read()
    except (FileNotFoundError, OSError):
        return f"*Plan submitted for review.*\n\n**Plan file:** `{plan_file}`\n"

    # Strip YAML frontmatter
    body = re.sub(r"\A---\n.*?\n---\n?", "", raw, flags=re.DOTALL)

    # Collect non-empty lines for preview
    preview_lines: list[str] = []
    for line in body.splitlines():
        if line.strip():
            preview_lines.append(line)
            if len(preview_lines) >= max_preview_lines:
                break

    preview = "\n".join(f"> {line}" for line in preview_lines)

    parts = [
        "*Plan submitted for review.*",
        "",
        f"**Plan file:** `{plan_file}`",
        "",
        preview,
    ]
    if len(preview_lines) >= max_preview_lines:
        parts.append("")
        parts.append("*See full plan file for details.*")

    return "\n".join(parts) + "\n"
