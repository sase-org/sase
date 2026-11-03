"""Tests for the confirm kill modal."""

from sase.ace.tui.modals.confirm_kill_modal import ConfirmKillModal


def test_confirm_kill_modal_bindings() -> None:
    """Test that ConfirmKillModal has expected bindings."""

    def get_key(binding: object) -> str:
        if hasattr(binding, "key"):
            return str(binding.key)  # type: ignore[attr-defined]
        return str(binding[0])  # type: ignore[index]

    bindings = [get_key(b) for b in ConfirmKillModal.BINDINGS]
    assert "escape" in bindings
    assert "q" in bindings
    assert "y" in bindings
    assert "n" in bindings


def test_confirm_kill_modal_empty_description() -> None:
    """Test ConfirmKillModal with empty description."""
    modal = ConfirmKillModal(agent_description="")
    assert modal.agent_description == ""


def test_confirm_kill_modal_hijack_choice_is_opt_in() -> None:
    normal = ConfirmKillModal(agent_description="agent")
    assert normal.hijack_available is False
    assert "Hijack instead" not in normal._message

    eligible = ConfirmKillModal(
        agent_description="agent",
        hijack_available=True,
        workspace_num=4,
    )
    assert "h Hijack instead" in eligible._message
    assert "workspace #4" in eligible._message
