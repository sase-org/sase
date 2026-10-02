"""``PagerScreen``: the thin host around one (later two) ``PagerView``s.

This module is the public import path facade: the implementation lives
in the sibling ``_screen_host`` and ``_screen_split`` modules and is
re-exported here as :class:`PagerScreen`. The ``resolve_ref``,
``subprocess``, ``suspend_for_external_tool``, and ``view_artifact_files``
attributes stay on this module so existing ``monkeypatch`` targets keep
working.
"""

from __future__ import annotations

import subprocess

from textual.binding import Binding
from textual.screen import ModalScreen

from sase.ace.tui.graphics import view_artifact_files
from sase.ace.tui.util.external_tool import suspend_for_external_tool
from sase.pager._screen_host import PagerScreenHostMixin
from sase.pager._screen_split import PagerScreenSplitMixin
from sase.pager._styles import PAGER_CSS
from sase.pager.app import PagerExit
from sase.pager.resolve import resolve_link as resolve_ref

__all__ = [
    "PagerScreen",
    "resolve_ref",
    "subprocess",
    "suspend_for_external_tool",
    "view_artifact_files",
]


class PagerScreen(  # type: ignore[misc]
    PagerScreenHostMixin,
    PagerScreenSplitMixin,
    ModalScreen[PagerExit],
):
    """Host one focused ``PagerView`` plus the shared footer.

    The constructor signature is unchanged; per-document actions bound
    here dispatch to same-named ``action_*`` methods on the focused
    view.
    """

    CSS = PAGER_CSS

    BINDINGS = [
        Binding("left_parenthesis", "history_older", "Older", show=False),
        Binding("right_parenthesis", "history_newer", "Newer", show=False),
        Binding("left_curly_bracket", "history_first", "First", show=False),
        Binding("right_curly_bracket", "history_now", "Now", show=False),
        Binding("equals_sign", "history_toggle_diff", "Diff", show=False),
        Binding("at", "history_timeline", "Timeline", show=False),
        Binding(
            "left_square_bracket", "history_prev_change", "Prev change", show=False
        ),
        Binding(
            "right_square_bracket", "history_next_change", "Next change", show=False
        ),
        Binding("q,escape", "close_pager", "Close"),
        Binding("j,down", "scroll_down", "Down"),
        Binding("k,up", "scroll_up", "Up"),
        Binding("ctrl+d", "scroll_half_down", "Half Down"),
        Binding("ctrl+u", "scroll_half_up", "Half Up"),
        Binding("g", "scroll_top", "Top"),
        Binding("G", "scroll_bottom", "Bottom"),
        Binding("semicolon,colon", "goto_line", "Go to Line"),
        Binding("ctrl+n", "next_section", "Next Section"),
        Binding("ctrl+p", "prev_section", "Prev Section"),
        Binding("backspace,ctrl+o", "trail_back", "Back"),
        Binding("tab,ctrl+i", "trail_forward", "Forward", key_display="<ctrl+i>"),
        Binding("r", "refresh", "Refresh"),
        Binding("y", "arm_copy", "Copy"),
        Binding("E", "arm_edit", "Edit"),
        Binding("ctrl+w", "arm_other", "Other pane", show=False),
        Binding("question_mark", "show_help", "Keys"),
        Binding("backslash", "split_below", "Split below", show=False),
        Binding("vertical_line", "split_beside", "Split beside", show=False),
        Binding("ctrl+f", "focus_other", "Focus next pane", show=False),
        Binding("ctrl+b", "focus_other_reverse", "Focus previous pane", show=False),
        Binding(
            "ctrl+shift+f,greater_than_sign",
            "swap_pane_next",
            "Swap with next pane",
            show=False,
        ),
        Binding(
            "ctrl+shift+b,less_than_sign",
            "swap_pane_prev",
            "Swap with previous pane",
            show=False,
        ),
        Binding(
            "ctrl+shift+d,ctrl+x",
            "close_focused_pane",
            "Close focused pane",
            show=False,
        ),
        Binding("ctrl+t", "turn_split", "Turn split", show=False),
        Binding("plus", "grow_pane", "Grow pane", show=False),
        Binding("minus", "shrink_pane", "Shrink pane", show=False),
    ]
