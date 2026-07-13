"""Tests for ``sase init`` inventory and diff rendering."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

from rich.console import Console

from sase.main.init_plan import InitAction, InitPlan
from sase.main.init_preview import _action_diffstat, render_plan_diff


def _console(output: StringIO) -> Console:
    return Console(
        file=output,
        force_terminal=False,
        no_color=True,
        soft_wrap=True,
        width=100,
    )


def _plan(action: InitAction) -> InitPlan:
    return InitPlan("memory", "Memory", "", (action,))


def test_action_diffstat_counts_create_update_delete_and_missing(
    tmp_path: Path,
) -> None:
    current = tmp_path / "current.md"
    current.write_text("old\nsame\n", encoding="utf-8")

    update = _action_diffstat(
        InitAction(current, "update", new_content="new\nsame\nadded\n")
    )
    create = _action_diffstat(
        InitAction(tmp_path / "new.md", "create", new_content="one\ntwo\n")
    )
    delete = _action_diffstat(InitAction(current, "delete"))
    procedural = _action_diffstat(
        InitAction(tmp_path / "remote", "create", "create sidecar repository")
    )

    assert update is not None
    assert (update.added, update.removed) == (2, 1)
    assert create is not None
    assert (create.added, create.removed) == (2, 0)
    assert delete is not None
    assert (delete.added, delete.removed) == (0, 2)
    assert procedural is None


def test_action_diffstat_reports_binary_sizes(tmp_path: Path) -> None:
    target = tmp_path / "map.png"
    target.write_bytes(b"old")

    stat = _action_diffstat(
        InitAction(target, "update", new_content=b"new binary bytes")
    )

    assert stat is not None
    assert stat.binary is True
    assert (stat.old_size, stat.new_size) == (3, 16)


def test_render_plan_diff_shows_delete_lines_and_has_no_ansi(
    tmp_path: Path,
) -> None:
    target = tmp_path / "legacy.md"
    target.write_text("first\nsecond\n", encoding="utf-8")
    output = StringIO()

    render_plan_diff(_console(output), _plan(InitAction(target, "delete", "legacy")))

    rendered = output.getvalue()
    assert "Removes 2 lines." in rendered
    assert "-first" in rendered
    assert "-second" in rendered
    assert "\x1b[" not in rendered


def test_render_plan_diff_summarizes_binary_and_procedural_actions(
    tmp_path: Path,
) -> None:
    binary = tmp_path / "map.png"
    binary.write_bytes(b"x" * 1500)
    plan = InitPlan(
        "sdd",
        "SDD",
        "",
        (
            InitAction(binary, "update", "directory map", b"y" * 2500),
            InitAction(
                tmp_path / "remote",
                "create",
                "create or connect the provider sidecar SDD repository",
            ),
        ),
    )
    output = StringIO()

    render_plan_diff(_console(output), plan)

    rendered = output.getvalue()
    assert "Binary file differs: 1.5 kB on disk → 2.5 kB generated." in rendered
    assert "Remote/procedural action — no local file diff." in rendered
    assert "A separate y/N confirmation guards sidecar repository creation." in rendered
