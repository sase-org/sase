"""Import-cost guards for broad ACE TUI package surfaces."""

from __future__ import annotations

import subprocess
import sys
import textwrap


def _run_probe(source: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_widget_submodule_import_does_not_import_app_or_all_widgets() -> None:
    _run_probe(
        """
        import sys
        import sase.ace.tui.widgets.task_indicator

        assert "sase.ace.tui.app" not in sys.modules
        assert "sase.ace.tui.widgets.agent_detail" not in sys.modules
        assert "sase.ace.tui.widgets.artifacts.beads_pane" not in sys.modules
        """
    )


def test_selection_item_import_stays_off_the_project_select_modal() -> None:
    _run_probe(
        """
        import sys
        from sase.ace.tui.modals import SelectionItem

        selection = SelectionItem("[P] demo", "project", "demo", None)

        assert selection.option_id == "project:demo"
        assert "sase.ace.tui.modals.project_select_modal" not in sys.modules
        """
    )


def test_clipboard_delivery_import_stays_off_clipboard_mixins() -> None:
    _run_probe(
        """
        import sys
        from sase.ace.tui.actions.clipboard import schedule_copy_delivery

        assert callable(schedule_copy_delivery)
        assert "sase.ace.tui.actions.clipboard._agents" not in sys.modules
        assert "sase.ace.tui.actions.clipboard._core" not in sys.modules
        """
    )
