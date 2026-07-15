"""Tests for the ``sase update`` change-set summary and Rich rendering."""

from __future__ import annotations

import io

from rich.console import Console

from sase.uv_tool.receipt import parse_receipt
from sase.uv_tool.render import (
    PlannedPackage,
    UpdateOutcome,
    UpdateSummary,
    render_update_dry_run,
    render_update_result,
    render_uv_tool_error,
    summarize_planned_update,
    summarize_update,
)
from sase.uv_tool.runner import ChangeKind, parse_uv_output

_RECEIPT = """
[tool]
requirements = [
    { name = "sase" },
    { name = "sase-github" },
    { name = "sase-telegram" },
]
"""

# A dev receipt: editable entries plus bare index dups of two plugins, exactly
# what `uv tool install sase` records for an editable dev checkout.
_DEV_RECEIPT = """
[tool]
requirements = [
    { name = "sase", editable = "/home/u/sase" },
    { name = "sase-core-rs", editable = "/home/u/sase-core/py" },
    { name = "sase-github", editable = "/home/u/sase-github" },
    { name = "sase-telegram", editable = "/home/u/sase-telegram" },
    { name = "sase-github" },
    { name = "sase-telegram" },
]
"""

# sase + sase-github upgraded; sase-telegram untouched (no line).
_UPGRADE_OUTPUT = """\
Resolved 3 packages in 120ms
 - sase==0.5.0
 + sase==0.6.1
 - sase-github==0.3.2
 + sase-github==0.4.0
Installed 1 executable: sase
"""


def _versions(mapping: dict[str, str]):
    return lambda name: mapping.get(name)


def _render(summary: UpdateSummary, *, elapsed: float | None = 4.2) -> str:
    console = Console(file=io.StringIO(), width=200, no_color=True)
    render_update_result(summary, elapsed=elapsed, console=console)
    return console.file.getvalue()  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# summarize_update
# --------------------------------------------------------------------------- #


def test_summarize_merges_receipt_and_change_set() -> None:
    summary = summarize_update(
        parse_uv_output(_UPGRADE_OUTPUT),
        parse_receipt(_RECEIPT),
        current_version=_versions({"sase-telegram": "0.1.0"}),
    )

    assert [(o.name, o.role, o.kind) for o in summary.outcomes] == [
        ("sase", "primary", ChangeKind.UPGRADED),
        ("sase-github", "plugin", ChangeKind.UPGRADED),
        ("sase-telegram", "plugin", ChangeKind.UNCHANGED),
    ]
    telegram = summary.outcomes[-1]
    assert telegram.new_version == "0.1.0"  # current version for unchanged
    assert summary.changed is True
    assert summary.primary_updated is True
    assert [o.name for o in summary.updated_plugins] == ["sase-github"]
    assert [o.name for o in summary.already_current] == ["sase-telegram"]


def test_summarize_planned_update_reports_transitive_core_transition() -> None:
    summary = summarize_planned_update(
        parse_uv_output(" - sase-core-rs==0.4.0\n + sase-core-rs==0.4.1"),
        (
            PlannedPackage(
                name="sase-core-rs",
                role="dependency",
                current_version="0.4.0",
            ),
        ),
    )

    assert summary.outcomes == (
        UpdateOutcome(
            name="sase-core-rs",
            role="dependency",
            kind=ChangeKind.UPGRADED,
            old_version="0.4.0",
            new_version="0.4.1",
        ),
    )


def test_summarize_dedupes_duplicate_dev_receipt_plugins() -> None:
    summary = summarize_update(
        parse_uv_output("Nothing to upgrade\n"),
        parse_receipt(_DEV_RECEIPT),
        current_version=_versions(
            {
                "sase": "0.6.1",
                "sase-core-rs": "0.6.1",
                "sase-github": "0.4.0",
                "sase-telegram": "0.1.0",
            }
        ),
    )

    # One outcome per distribution: no duplicated sase-github / sase-telegram.
    assert [o.name for o in summary.outcomes] == [
        "sase",
        "sase-core-rs",
        "sase-github",
        "sase-telegram",
    ]
    assert len(summary.already_current) == 4
    assert all(o.kind is ChangeKind.UNCHANGED for o in summary.outcomes)


def test_summarize_orders_primary_then_plugins_then_dependencies() -> None:
    output = """\
 - sase==0.5.0
 + sase==0.6.1
 - charset-normalizer==3.0.0
 + charset-normalizer==3.4.0
"""
    summary = summarize_update(
        parse_uv_output(output),
        parse_receipt(_RECEIPT),
        current_version=_versions({"sase-github": "0.4.0", "sase-telegram": "0.1.0"}),
    )

    roles = [o.role for o in summary.outcomes]
    # Receipt packages (primary, plugins) lead; the transitive dep trails.
    assert roles == ["primary", "plugin", "plugin", "dependency"]
    dep = summary.outcomes[-1]
    assert dep.name == "charset-normalizer"
    assert [o.name for o in summary.updated_dependencies] == ["charset-normalizer"]


def test_summarize_without_receipt_infers_primary() -> None:
    summary = summarize_update(
        parse_uv_output(" - sase==1\n + sase==2\n + extra==9\n"),
        None,
        current_version=_versions({}),
    )

    assert summary.outcomes[0].name == "sase"
    assert summary.outcomes[0].role == "primary"
    assert summary.outcomes[1].role == "dependency"


def test_summarize_noop_marks_everything_current() -> None:
    summary = summarize_update(
        parse_uv_output("Nothing to upgrade\n"),
        parse_receipt(_RECEIPT),
        current_version=_versions(
            {"sase": "0.6.1", "sase-github": "0.4.0", "sase-telegram": "0.1.0"}
        ),
    )

    assert summary.changed is False
    assert len(summary.already_current) == 3
    assert summary.updated == ()


def test_summarize_handles_added_and_removed() -> None:
    summary = summarize_update(
        parse_uv_output(" + sase-github==0.4.0\n - sase-telegram==0.1.0\n"),
        parse_receipt(_RECEIPT),
        current_version=_versions({"sase": "0.6.1"}),
    )

    by_name = {o.name: o for o in summary.outcomes}
    assert by_name["sase-github"].kind is ChangeKind.ADDED
    assert by_name["sase-telegram"].kind is ChangeKind.REMOVED
    assert [o.name for o in summary.removed] == ["sase-telegram"]


# --------------------------------------------------------------------------- #
# render_update_result
# --------------------------------------------------------------------------- #


def test_render_result_shows_transitions_and_summary() -> None:
    summary = summarize_update(
        parse_uv_output(_UPGRADE_OUTPUT),
        parse_receipt(_RECEIPT),
        current_version=_versions({"sase-telegram": "0.1.0"}),
    )
    out = _render(summary)

    assert "0.5.0 → 0.6.1" in out
    assert "0.3.2 → 0.4.0" in out
    assert "already current" in out
    assert "Updated sase + 1 plugin in 4.2s · 1 already current" in out
    assert "Restart running sase agents" in out


def test_render_result_pluralizes_plugins() -> None:
    output = """\
 - sase==0.5.0
 + sase==0.6.1
 - sase-github==0.3.2
 + sase-github==0.4.0
 - sase-telegram==0.1.0
 + sase-telegram==0.2.0
"""
    summary = summarize_update(
        parse_uv_output(output), parse_receipt(_RECEIPT), current_version=_versions({})
    )
    out = _render(summary)

    assert "Updated sase + 2 plugins in 4.2s" in out


def test_render_result_up_to_date_when_nothing_changed() -> None:
    summary = UpdateSummary(
        (UpdateOutcome("sase", "primary", ChangeKind.UNCHANGED, new_version="0.6.1"),)
    )
    out = _render(summary)

    assert "Already up to date" in out
    assert "Restart running sase agents" not in out


def test_render_result_quiet_is_one_line() -> None:
    summary = summarize_update(
        parse_uv_output(_UPGRADE_OUTPUT),
        parse_receipt(_RECEIPT),
        current_version=_versions({"sase-telegram": "0.1.0"}),
    )
    console = Console(file=io.StringIO(), width=200, no_color=True)
    render_update_result(summary, elapsed=4.2, quiet=True, console=console)
    out = console.file.getvalue()  # type: ignore[attr-defined]

    assert out.strip() == "Updated sase + 1 plugin in 4.2s · 1 already current"


def test_render_result_quiet_up_to_date() -> None:
    summary = UpdateSummary(
        (UpdateOutcome("sase", "primary", ChangeKind.UNCHANGED, new_version="0.6.1"),)
    )
    console = Console(file=io.StringIO(), width=200, no_color=True)
    render_update_result(summary, elapsed=1.0, quiet=True, console=console)

    assert console.file.getvalue().strip() == "Already up to date."  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# render_update_dry_run / errors
# --------------------------------------------------------------------------- #


def test_render_dry_run_shows_command_and_packages() -> None:
    argv = ["uv", "tool", "upgrade", "--color", "never", "sase"]
    packages = (
        PlannedPackage("sase", "primary", "0.5.0"),
        PlannedPackage("sase-github", "plugin", "0.3.2"),
    )
    console = Console(file=io.StringIO(), width=200, no_color=True)
    render_update_dry_run(argv, packages, console=console)
    out = console.file.getvalue()  # type: ignore[attr-defined]

    assert "uv tool upgrade --color never sase" in out
    assert "v0.5.0" in out
    assert "sase core" in out
    assert "plugin" in out
    assert "Dry run" in out


def test_render_dry_run_with_empty_set() -> None:
    console = Console(file=io.StringIO(), width=200, no_color=True)
    render_update_dry_run(["uv", "tool", "upgrade", "sase"], (), console=console)

    assert "No packages found" in console.file.getvalue()  # type: ignore[attr-defined]


def test_render_error_goes_to_console() -> None:
    console = Console(file=io.StringIO(), width=200, no_color=True)
    render_uv_tool_error("sase is not a uv tool install", console=console)

    output = console.file.getvalue()  # type: ignore[attr-defined]
    assert "sase is not a uv tool install" in output
    # Fatal errors use the red ✗ glyph; ⚠ stays reserved for yellow warnings,
    # matching the catalog renderer's legend.
    assert "✗" in output
    assert "⚠" not in output


def test_summarize_uses_receipt_name_casing() -> None:
    # uv prints a normalized/odd-cased name; the receipt name should win.
    summary = summarize_update(
        parse_uv_output(" - Sase_GitHub==0.3.2\n + Sase_GitHub==0.4.0\n"),
        parse_receipt(_RECEIPT),
        current_version=_versions({"sase": "0.6.1", "sase-telegram": "0.1.0"}),
    )

    github = next(o for o in summary.outcomes if o.role == "plugin" and o.is_update)
    assert github.name == "sase-github"
    assert github.new_version == "0.4.0"
