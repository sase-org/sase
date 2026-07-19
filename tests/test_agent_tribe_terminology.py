"""Prevent current agent-tribe surfaces from drifting back to tag terminology."""

from __future__ import annotations

import re
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]

_TAG_IDENTIFIER_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:agent_tags?|AgentTag[A-Za-z0-9_]*|"
    r"tag_panel[A-Za-z0-9_]*|panel_tag[A-Za-z0-9_]*|"
    r"tag_scope[A-Za-z0-9_]*|tagged_artifact[A-Za-z0-9_]*)",
)

# These files either read the legacy agent_tags.json shape or deal with the
# unrelated SASE_AGENT commit-provenance tag. New exceptions should be rare and
# must identify an equally explicit migration or unrelated-tag boundary.
_TAG_IDENTIFIER_ALLOWLIST = {
    Path("src/sase/core/agent_tribe.py"),
    Path("src/sase/core/wait_dependency_resolution/_index.py"),
    Path("src/sase/ace/agent_tribes.py"),
    Path("src/sase/ace/revert_agent.py"),
    Path("src/sase/ace/revert_agent_discovery.py"),
    Path("src/sase/ace/revert_agent_execute.py"),
    Path("src/sase/ace/revert_agent_models.py"),
    Path("src/sase/axe/image_attachments.py"),
}

_CURRENT_DOCUMENTATION = (
    Path("docs/ace.md"),
    Path("docs/agent_families.md"),
    Path("docs/xprompt.md"),
    Path("sase/memory/cli_rules.md"),
)

_STALE_DOCUMENTATION_PHRASES = (
    "sase agent tag",
    "(untagged)",
    "tribe/tag chooser",
    "tag-split panels",
    "post-hoc member tags",
    "post-hoc tags for named standalone agents",
    "Clan `@tribe` tags",
    "A tagged clan member",
    "`provider`, `tag`, `text`",
    "tag, clan, marked, group, and custom planner-backed selections",
)


def test_current_source_avoids_agent_tag_identifiers() -> None:
    findings: list[str] = []
    for path in sorted((_ROOT / "src").rglob("*.py")):
        relative = path.relative_to(_ROOT)
        if relative in _TAG_IDENTIFIER_ALLOWLIST:
            continue
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if _TAG_IDENTIFIER_RE.search(line):
                findings.append(f"{relative}:{line_number}: {line.strip()}")

    assert findings == []


def test_current_documentation_avoids_stale_agent_tribe_phrases() -> None:
    findings: list[str] = []
    for relative in _CURRENT_DOCUMENTATION:
        content = (_ROOT / relative).read_text(encoding="utf-8")
        for phrase in _STALE_DOCUMENTATION_PHRASES:
            if phrase in content:
                findings.append(f"{relative}: {phrase}")

    assert findings == []
