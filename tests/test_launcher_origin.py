"""AST enforcement: every in-tree launcher call passes ``origin=`` explicitly."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]
SRC = ROOT / "src" / "sase"

LAUNCHER_CALLS = {
    "launch_agents_from_cwd",
    "launch_agent_from_cwd",
    "launch_planned_bead_work_agents",
    "launch_agents_from_cwd_fn",
    "launch_agent_from_cwd_fn",
}


def test_every_launcher_call_passes_origin_explicitly() -> None:
    """Fail when a launcher call omits the ``origin=`` keyword.

    The launcher ``origin`` default stays ``None`` (which still records), so
    an omitted keyword silently records machine launches as human history.
    Every in-tree call — by bare name or by attribute — must state its
    provenance outright. This is the fail-closed guarantee for future
    automation surfaces.
    """
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _call_name(node.func) not in LAUNCHER_CALLS:
                continue
            if not any(keyword.arg == "origin" for keyword in node.keywords):
                rel = path.relative_to(ROOT)
                offenders.append(f"{rel}:{node.lineno}")
    assert offenders == []


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""
