"""Footer tests for the contextual leader ``,x`` kill-and-edit binding.

``,x`` reads ``kill marked & edit (N)`` in the Agents-tab leader footer when
marks exist (carrying the marked-agent count) and ``kill & edit`` otherwise.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from sase.ace.tui.widgets import KeybindingFooter


def _capture_leader(
    *, current_tab: str, marked_agent_count: int
) -> list[tuple[str, str]]:
    footer = KeybindingFooter()
    captured: list[tuple[list[tuple[str, str]], str | None]] = []
    footer._update_display = MagicMock(  # type: ignore[method-assign]
        side_effect=lambda bindings, mode_label=None: captured.append(
            (list(bindings), mode_label)
        )
    )
    footer.update_leader_bindings(
        current_tab=current_tab, marked_agent_count=marked_agent_count
    )
    assert captured, "footer never updated"
    return captured[-1][0]


def test_kill_marked_edit_shown_on_agents_tab_with_marks() -> None:
    bindings = _capture_leader(current_tab="agents", marked_agent_count=3)
    assert ("x", "kill marked & edit (3)") in bindings


def test_kill_marked_edit_hidden_without_marks() -> None:
    bindings = _capture_leader(current_tab="agents", marked_agent_count=0)
    assert not any(label.startswith("kill marked & edit") for _, label in bindings)
    # Single-row kill-and-edit is always offered on the Agents tab.
    assert any(label == "kill & edit" for _, label in bindings)


def test_kill_marked_edit_absent_off_agents_tab() -> None:
    bindings = _capture_leader(current_tab="patches", marked_agent_count=3)
    assert not any(label.startswith("kill marked & edit") for _, label in bindings)
