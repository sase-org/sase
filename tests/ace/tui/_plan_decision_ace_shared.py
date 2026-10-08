"""Shared fixtures for the ``test_plan_decision_ace_*`` test modules.

Public helpers used by more than one split module live here under public
names so no new module imports a ``_``-prefixed name from another new
module.
"""

from __future__ import annotations

__all__ = [
    "plan_decision_definitions",
]


def plan_decision_definitions(tmp_path) -> list[dict]:
    """Real gate payload definitions (no artifacts dir => quote_not_found)."""
    import textwrap

    content = textwrap.dedent(
        """\
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
    )
    plan_path = str(tmp_path / "defs_plan.md")
    import pathlib as _pathlib

    _pathlib.Path(plan_path).write_text(content, encoding="utf-8")
    from sase.plan_gate import build_plan_approval_gate_spec

    spec = build_plan_approval_gate_spec(plan_path, "visual-session")
    decisions = spec["payload"]["decisions"]
    assert isinstance(decisions, list) and len(decisions) == 2
    return [dict(item) for item in decisions if isinstance(item, dict)]
