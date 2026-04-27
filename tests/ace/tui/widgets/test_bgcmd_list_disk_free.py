"""``BgCmdList.update_list`` must not read axe config from disk.

Phase 7 of the TUI perf overhaul moves the lumberjack-count lookup from
``load_axe_config()`` (a disk read on every row render) to the
caller-provided ``lumberjack_names`` list. This test pins that invariant.
"""

from __future__ import annotations

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.bgcmd_list import (
    AxeParentItem,
    BgCmdList,
    LumberjackItem,
)


class _Host(App):
    def compose(self) -> ComposeResult:
        yield BgCmdList(id="bgcmd-list")


async def test_update_list_does_not_call_load_axe_config(
    monkeypatch,
) -> None:
    """Rendering parent + lumberjack items must skip ``load_axe_config``."""
    calls = 0

    def _trip(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("load_axe_config must not run from row render")

    monkeypatch.setattr("sase.axe.config.load_axe_config", _trip)

    app = _Host()
    async with app.run_test():
        widget = app.query_one(BgCmdList)
        items = [
            AxeParentItem(),
            LumberjackItem(name="alpha"),
            LumberjackItem(name="beta"),
        ]
        widget.update_list(
            items=items,
            current_idx=0,
            axe_running=False,
            lumberjack_names=["alpha", "beta", "gamma"],
            bgcmd_infos={},
            lumberjack_statuses={"alpha": None, "beta": None},
            bgcmd_running={},
        )

    assert calls == 0
