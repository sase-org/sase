"""Prevent current agent-tribe surfaces from drifting back to tag terminology."""

from __future__ import annotations

import re
from pathlib import Path


import pytest

pytestmark = pytest.mark.contract

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
    # Serializes RevertCommit.agent_tag (commit-provenance, not tribe).
    Path("src/sase/ops/commands/_agent_revert.py"),
    # Mirrors agent_tagged_commits in the commit-provenance statistics wire.
    Path("src/sase/stats/project/models.py"),
    # Reads agent_tagged_commits from the commit-provenance statistics wire.
    Path("src/sase/stats/render/legend.py"),
}

_CURRENT_DOCUMENTATION = (
    Path("docs/reference/agents/agent-clans.md"),
    Path("docs/reference/agents/agent-sessions.md"),
    Path("docs/reference/agents/agent-tribes.md"),
    Path("docs/reference/agents/agent-launches.md"),
    Path("docs/reference/tui/agents-tab.md"),
    Path("docs/reference/tui/agents-tab-modes.md"),
    Path("docs/reference/tui/agents-tab-panels.md"),
    Path("docs/reference/tui/agents-tab-grouping.md"),
    Path("docs/reference/tui/agent-row-glyphs.md"),
    Path("docs/reference/tui/agent-statuses.md"),
    Path("docs/reference/tui/agents-main-deck.md"),
    Path("docs/reference/tui/agents-deck-panels.md"),
    Path("docs/reference/tui/agent-workflows.md"),
    Path("docs/reference/tui/prompt-input.md"),
    Path("docs/reference/tui/prompt-modes.md"),
    Path("docs/reference/tui/prompt-stacks.md"),
    Path("docs/reference/tui/prompt-completion.md"),
    Path("docs/reference/tui/prompt-completion-panels.md"),
    Path("docs/reference/tui/prompts-overlay.md"),
    Path("docs/reference/tui/snippets.md"),
    Path("docs/reference/tui/launch-control.md"),
    Path("docs/reference/tui/launch-control-overrides.md"),
    Path("docs/reference/tui/launching.md"),
    Path("docs/reference/tui/tabs-and-panes.md"),
    Path("docs/reference/tui/filtering.md"),
    Path("docs/reference/tui/files-and-preview.md"),
    Path("docs/reference/tui/artifacts-tab.md"),
    Path("docs/reference/tui/services-tab.md"),
    Path("docs/reference/tui/query-system.md"),
    Path("docs/reference/tui/machines-and-tools.md"),
    Path("docs/reference/tui/projects-tab.md"),
    Path("docs/reference/tui/global-controls.md"),
    Path("docs/reference/tui/notifications-modal.md"),
    Path("docs/reference/tui/finders.md"),
    Path("docs/reference/tui/procs-tab.md"),
    Path("docs/reference/tui/updates-tab.md"),
    Path("docs/reference/tui/pager.md"),
    Path("docs/contribute/tui-rendering.md"),
    Path("docs/reference/macros/arguments.md"),
    Path("docs/reference/macros/built-ins.md"),
    Path("docs/reference/macros/cli-and-editor.md"),
    Path("docs/reference/macros/directive-composition.md"),
    Path("docs/reference/macros/directive-launch.md"),
    Path("docs/reference/macros/directive-syntax.md"),
    Path("docs/reference/macros/discovery.md"),
    Path("docs/reference/macros/discovery-order.md"),
    Path("docs/reference/macros/fields.md"),
    Path("docs/reference/macros/index.md"),
    Path("docs/reference/macros/multi-agent-prompts.md"),
    Path("docs/reference/macros/reference-syntax.md"),
    Path("docs/reference/macros/tags.md"),
    Path("docs/reference/macros/templating.md"),
    Path("docs/reference/macros/troubleshooting.md"),
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
