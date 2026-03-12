"""Snapshot tests for status_state_machine.constants."""

from inline_snapshot import snapshot

from sase.status_state_machine.constants import (
    VALID_TRANSITIONS,
    is_valid_transition,
    remove_workspace_suffix,
)


class TestRemoveWorkspaceSuffix:
    def test_no_suffix(self) -> None:
        assert remove_workspace_suffix("Ready") == snapshot("Ready")

    def test_workspace_suffix(self) -> None:
        assert remove_workspace_suffix("Ready (fig_3)") == snapshot("Ready")

    def test_complex_project_name(self) -> None:
        assert remove_workspace_suffix("Draft (my-proj_12)") == snapshot("Draft")

    def test_legacy_ready_to_mail(self) -> None:
        assert remove_workspace_suffix("Ready - (!: READY TO MAIL)") == snapshot(
            "Ready"
        )

    def test_no_false_positive_for_parentheses(self) -> None:
        # Only strips pattern matching " (<project>_<N>)" at end
        assert remove_workspace_suffix("WIP (notes)") == snapshot("WIP (notes)")


class TestIsValidTransition:
    def test_wip_to_draft(self) -> None:
        assert is_valid_transition("WIP", "Draft") is True

    def test_wip_to_ready(self) -> None:
        assert is_valid_transition("WIP", "Ready") is True

    def test_draft_to_ready(self) -> None:
        assert is_valid_transition("Draft", "Ready") is True

    def test_ready_to_mailed(self) -> None:
        assert is_valid_transition("Ready", "Mailed") is True

    def test_ready_to_draft(self) -> None:
        assert is_valid_transition("Ready", "Draft") is True

    def test_mailed_to_submitted(self) -> None:
        assert is_valid_transition("Mailed", "Submitted") is True

    def test_invalid_wip_to_mailed(self) -> None:
        assert is_valid_transition("WIP", "Mailed") is False

    def test_invalid_submitted_to_anything(self) -> None:
        assert is_valid_transition("Submitted", "Ready") is False

    def test_invalid_reverted_to_anything(self) -> None:
        assert is_valid_transition("Reverted", "Ready") is False

    def test_invalid_from_status(self) -> None:
        assert is_valid_transition("Nonexistent", "Ready") is False

    def test_invalid_to_status(self) -> None:
        assert is_valid_transition("WIP", "Nonexistent") is False

    def test_workspace_suffix_stripped(self) -> None:
        assert is_valid_transition("Ready (fig_1)", "Draft") is True

    def test_valid_transitions_keys(self) -> None:
        assert sorted(VALID_TRANSITIONS.keys()) == snapshot(
            ["Archived", "Draft", "Mailed", "Ready", "Reverted", "Submitted", "WIP"]
        )
