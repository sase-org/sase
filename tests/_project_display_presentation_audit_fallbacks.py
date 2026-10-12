"""Project-display-name fallback audit and reviewed exemptions."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

from _project_display_presentation_audit_helpers import (
    enclosing_function,
    parent_map,
    parse_source,
)

pytestmark = pytest.mark.contract
_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class _DisplayFallbackExemption:
    path: str
    function: str
    expression: str
    rationale: str


# Pre-existing ``project_display_name or ...`` fallbacks outside the agent-label
# chokepoint. Each owns a non-Agent display field or a query/entry identity where
# the fallback is empty or the model carries its own refresh story.
_DISPLAY_FALLBACK_EXEMPTIONS = (
    _DisplayFallbackExemption(
        "src/sase/ace/tui/bgcmd.py",
        "display_project",
        "self.project_display_name or self.project",
        "Durable oneshot rows snapshot their label at build time and refresh on rebuild.",
    ),
    _DisplayFallbackExemption(
        "src/sase/ace/patch/models/patch.py",
        "project_query_name",
        "self.project_display_name or self.project_name",
        "Exact project: query identity, not a painted label.",
    ),
    _DisplayFallbackExemption(
        "src/sase/artifact_providers/builtin_entry_patch.py",
        "resolve_patch_entry",
        "patch.project_display_name or ''",
        "Entry builder falls back to empty, never to a key.",
    ),
    _DisplayFallbackExemption(
        "src/sase/ace/tui/widgets/prompt_panel/_identity_header_compact.py",
        "_build_named_proc_compact_lines",
        "agent.project_display_name or humanize_cl_name(agent.cl_name)",
        "Named-proc rows fall back to the proc's own name, never a path or key.",
    ),
    _DisplayFallbackExemption(
        "src/sase/ace/tui/widgets/prompt_panel/_agent_display_header_metadata_identity.py",
        "append_project_fields",
        "agent.project_display_name or humanize_cl_name(agent.cl_name)",
        "Named-proc fields fall back to the proc's own name, never a path or key.",
    ),
)

# The sanctioned chokepoint: ``Agent.project_label`` plus the display-map module.
_DISPLAY_FALLBACK_CHOKPOINT = (
    "src/sase/ace/tui/models/agent.py",
    "project_label",
)
_DISPLAY_FALLBACK_CHOKPOINT_FILES = frozenset(
    {
        "src/sase/project_display_names.py",
    }
)


def _display_fallback_sites() -> dict[tuple[str, str, str], int]:
    """Map ``(path, function, or-expression)`` display fallbacks across ``src``."""
    sites: dict[tuple[str, str, str], int] = {}
    for file_path in sorted(_ROOT.glob("src/**/*.py")):
        if "__pycache__" in str(file_path):
            continue
        path = str(file_path.relative_to(_ROOT))
        tree = parse_source(path)
        parents = parent_map(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.BoolOp) or not isinstance(node.op, ast.Or):
                continue
            if not any(
                isinstance(value, ast.Attribute)
                and value.attr == "project_display_name"
                for value in node.values
            ):
                continue
            key = (path, enclosing_function(node, parents), ast.unparse(node))
            sites[key] = node.lineno
    return sites


def test_project_display_name_fallback_lives_only_in_chokepoint() -> None:
    """Only Agent.project_label may fall back from project_display_name."""
    allowed = {
        (item.path, item.function, item.expression)
        for item in _DISPLAY_FALLBACK_EXEMPTIONS
    }
    violations: list[str] = []
    for (path, function, expression), lineno in _display_fallback_sites().items():
        if path in _DISPLAY_FALLBACK_CHOKPOINT_FILES:
            continue
        if (path, function) == _DISPLAY_FALLBACK_CHOKPOINT:
            continue
        if (path, function, expression) in allowed:
            continue
        violations.append(f"{path}:{lineno} {function} falls back in {expression}")
    assert not violations, "\n".join(violations)


def test_display_fallback_exemptions_name_existing_sites_and_rationales() -> None:
    """Display-fallback exemptions are deliberate, documented, and cannot go stale."""
    actual = set(_display_fallback_sites())
    assert not any(key[0] in _DISPLAY_FALLBACK_CHOKPOINT_FILES for key in actual), (
        "display-map module grew a project_display_name fallback; review it here"
    )
    for exemption in _DISPLAY_FALLBACK_EXEMPTIONS:
        assert exemption.rationale.strip()
        assert (exemption.path, exemption.function, exemption.expression) in actual, (
            f"stale display-fallback exemption: {exemption.path} "
            f"{exemption.function} {exemption.expression}"
        )
