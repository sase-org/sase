"""Shared real-gate fixtures for Plan Decisions PNG goldens."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.notification_gates.branches import GateBranchData

TALE_CHOICES_PLAN = """\
---
tier: tale
title: Keymap help overlay
goal: Pressing ? shows bindings.
size: small
decisions:
  grouping:
    ask: How should the overlay group bindings?
    choices:
      pane: By pane
      mode: By mode
    default: pane
    why: pane keeps order
  density:
    ask: How dense should the overlay be?
    choices:
      cozy: Cozy spacing
      compact: Compact spacing
    default: cozy
    why: cozy reads better
---
# Plan
Body grouping pane density.
> [!decision] grouping = pane Order by pane.
> [!decision] grouping = mode Order by mode.
> [!decision] density = cozy
Cozy branch.
> [!decision] density = compact
Compact branch.
"""

TALE_MEMORY_PLAN = """\
---
tier: tale
title: Keymap help overlay
goal: Pressing ? shows bindings.
size: small
decisions:
  grouping:
    ask: How should the overlay group bindings?
    choices:
      pane: By pane
      mode: By mode
    default: pane
    why: pane keeps order
  tui_note:
    ask: Record conventions in the tui memory note?
    memory: [tui.md]
    requested: and note the convention in the tui memory note xyz
    default: true
---
# Plan
Body grouping pane tui_note.
> [!decision] grouping = pane Order by pane.
> [!decision] grouping = mode Order by mode.
> [!decision] tui_note
Yes branch.
> [!decision] tui_note = no
No branch.
"""

MEMORY_QUOTE = "and note the convention in the tui memory note xyz"

EPIC_DECISIONS_PLAN = """\
---
tier: epic
title: Overlay program
goal: Ship overlays.
phases:
- id: a
  title: A work unit
  depends_on: []
  size: small
decisions:
  scope:
    ask: Which overlays ship first?
    choices:
      help: Help overlay
      palette: Command palette
    default: help
    why: help is smaller
---
# Plan
Body scope.
> [!decision] scope = help Help first.
> [!decision] scope = palette Palette first.
"""


def decision_gate_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    name: str,
    content: str,
    verified_memory: bool = False,
) -> tuple[Path, GateBranchData, list[dict]]:
    """Build real gate data for a decisions golden.

    Writes the plan to tmp and calls ``build_plan_approval_gate_spec``. With
    no artifacts dir a memory quote fails closed to ``quote_not_found`` (the
    unverified case); ``verified_memory=True`` plants the minimal artifacts
    dir (typed root prompt containing the requested quote) for the ``asked``
    case. The spec carries no ``branches`` list, so branches are derived from
    its canonical query exactly as gate creation does.
    """
    from sase.notification_gates.query import parse_gate_query
    from sase.plan_gate import build_plan_approval_gate_spec

    plan = tmp_path / name
    plan.write_text(content, encoding="utf-8")
    if verified_memory:
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir(exist_ok=True)
        (artifacts / "agent_meta.json").write_text(
            json.dumps({"prompt_origin": "typed"}), encoding="utf-8"
        )
        (artifacts / "submitted_prompt.md").write_text(
            f"Please do the work {MEMORY_QUOTE} thanks.\n", encoding="utf-8"
        )
        monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    else:
        monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    spec = build_plan_approval_gate_spec(plan, "visual-session")
    envelope = dict(spec)
    envelope["branches"] = [
        list(branch) for branch in parse_gate_query(spec["query"]).branches
    ]
    gate = GateBranchData.from_envelope(envelope)
    definitions = [
        dict(item)
        for item in spec["payload"].get("decisions", [])
        if isinstance(item, dict)
    ]
    assert definitions, "expected real decision definitions from the gate spec"
    return plan, gate, definitions
