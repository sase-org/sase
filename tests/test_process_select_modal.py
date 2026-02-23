"""Tests for the process select modal."""

from unittest.mock import patch

from sase.ace.tui.bgcmd import BackgroundCommandInfo
from sase.ace.tui.modals import ProcessSelection
from sase.ace.tui.modals.process_select_modal import ProcessSelectModal


def test_process_selection_axe() -> None:
    """Test ProcessSelection dataclass for axe process."""
    selection = ProcessSelection(
        process_type="axe",
        slot=None,
        display_name="sase axe",
        description="Stop the axe scheduler daemon",
    )
    assert selection.process_type == "axe"
    assert selection.slot is None
    assert selection.display_name == "sase axe"
    assert selection.description == "Stop the axe scheduler daemon"


def test_process_selection_bgcmd() -> None:
    """Test ProcessSelection dataclass for background command."""
    selection = ProcessSelection(
        process_type="bgcmd",
        slot=3,
        display_name="[3] make test",
        description="myproject (ws 1)",
    )
    assert selection.process_type == "bgcmd"
    assert selection.slot == 3
    assert selection.display_name == "[3] make test"
    assert selection.description == "myproject (ws 1)"


def test_process_selection_start_axe() -> None:
    """Test ProcessSelection dataclass for start_axe process."""
    selection = ProcessSelection(
        process_type="start_axe",
        slot=None,
        display_name="sase axe",
        description="Start the axe scheduler daemon",
    )
    assert selection.process_type == "start_axe"
    assert selection.slot is None
    assert selection.display_name == "sase axe"
    assert selection.description == "Start the axe scheduler daemon"


def test_process_selection_equality() -> None:
    """Test that ProcessSelection dataclass supports equality."""
    sel1 = ProcessSelection(
        process_type="axe",
        slot=None,
        display_name="sase axe",
        description="desc",
    )
    sel2 = ProcessSelection(
        process_type="axe",
        slot=None,
        display_name="sase axe",
        description="desc",
    )
    assert sel1 == sel2


def test_process_selection_with_background_command_info() -> None:
    """Test ProcessSelection created from BackgroundCommandInfo."""
    info = BackgroundCommandInfo(
        command="npm run build",
        project="webapp",
        workspace_num=2,
        workspace_dir="/path/to/workspace",
        started_at="2025-01-01T12:00:00",
    )
    selection = ProcessSelection(
        process_type="bgcmd",
        slot=5,
        display_name=f"[5] {info.command}",
        description=f"{info.project} (ws {info.workspace_num})",
    )
    assert selection.process_type == "bgcmd"
    assert selection.slot == 5
    assert "npm run build" in selection.display_name
    assert "webapp" in selection.description
    assert "ws 2" in selection.description


def test_process_select_modal_long_command_truncated() -> None:
    """Test that long commands are truncated in process display."""
    info = BackgroundCommandInfo(
        command="npm run build-with-all-deps-and-extras-and-more-stuff-here",
        project="myproject",
        workspace_num=1,
        workspace_dir="/path",
        started_at="2025-01-01T12:00:00",
    )
    modal = ProcessSelectModal(axe_running=False, bgcmd_slots=[(5, info)])
    # First process is start_axe, second is the bgcmd
    assert "..." in modal._processes[1].display_name


def test_process_select_modal_bindings() -> None:
    """Test that ProcessSelectModal has expected bindings."""

    # BINDINGS can contain Binding objects or tuples
    def get_key(binding: object) -> str:
        if hasattr(binding, "key"):
            return str(binding.key)  # type: ignore[attr-defined]
        return str(binding[0])  # type: ignore[index]

    bindings = [get_key(b) for b in ProcessSelectModal.BINDINGS]
    assert "escape" in bindings
    assert "q" in bindings
    assert "j" in bindings
    assert "k" in bindings


def test_process_select_modal_create_styled_label_start_axe() -> None:
    """Test _create_styled_label for start_axe process."""
    modal = ProcessSelectModal(axe_running=False, bgcmd_slots=[])
    proc = modal._processes[0]
    label = modal._create_styled_label(proc)
    label_str = str(label)
    assert "[START]" in label_str
    assert "sase axe" in label_str


def test_process_select_modal_create_styled_label_bgcmd() -> None:
    """Test _create_styled_label for bgcmd process (running)."""
    info = BackgroundCommandInfo(
        command="make test",
        project="myproject",
        workspace_num=1,
        workspace_dir="/path",
        started_at="2025-01-01T12:00:00",
    )
    # Mock is_slot_running to return True (simulate running process)
    with patch(
        "sase.ace.tui.modals.process_select_modal.is_slot_running", return_value=True
    ):
        modal = ProcessSelectModal(axe_running=True, bgcmd_slots=[(2, info)])
        proc = modal._processes[1]  # Index 1, since index 0 is now axe
        label = modal._create_styled_label(proc)
        label_str = str(label)
        assert "[STOP]" in label_str


def test_process_select_modal_create_options() -> None:
    """Test _create_options returns correct number of options."""
    info = BackgroundCommandInfo(
        command="make test",
        project="myproject",
        workspace_num=1,
        workspace_dir="/path",
        started_at="2025-01-01T12:00:00",
    )
    modal = ProcessSelectModal(axe_running=True, bgcmd_slots=[(1, info), (3, info)])
    options = modal._create_options()
    assert len(options) == 3  # axe + 2 bgcmds
