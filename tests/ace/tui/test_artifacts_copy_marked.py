"""Multi-mark coverage for Artifacts copy mode."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sase.ace.tui.widgets.artifacts.plans_list import PlanRow, plan_row_target
from tests.ace.tui._artifacts_copy_helpers import CopyHarness
from tests.ace.tui._artifacts_files_helpers import artifact_file


def test_marked_commits_copy_in_visual_order_with_labeled_sections() -> None:
    app = CopyHarness()
    entries = tuple(
        SimpleNamespace(
            repo="sase",
            commit=SimpleNamespace(
                full_id=character * 40,
                short_id=character * 7,
            ),
        )
        for character in ("a", "b")
    )
    targets = tuple(("commit", entry.repo, entry.commit.full_id) for entry in entries)
    app._artifacts_marked_targets = {"stitches": set(targets)}
    app.commits_pane = SimpleNamespace(
        result=SimpleNamespace(commits=entries),
        entry_targets=lambda: targets,
    )

    assert app._handle_copy_key("percent_sign") is True

    assert app.copies == [
        (
            "\n".join(
                (
                    "### sase@aaaaaaa",
                    "```",
                    "a" * 40,
                    "```",
                    "### sase@bbbbbbb",
                    "```",
                    "b" * 40,
                    "```",
                )
            ),
            "Copied 2 commit SHAs",
        )
    ]


def test_marked_plans_copy_the_marked_set() -> None:
    app = CopyHarness()
    app.current_artifacts_subtab = "plans"
    rows = tuple(
        PlanRow(
            "proposal",
            f"proposal-{index}",
            "alpha",
            proposal=SimpleNamespace(
                notification=SimpleNamespace(id=f"notice-{index}"),
                plan_path=f"/tmp/plan-{index}.md",
                title=f"Plan {index}",
                body=f"Body {index}",
            ),
        )
        for index in (1, 2)
    )
    targets = tuple(plan_row_target(row) for row in rows)
    app._artifacts_marked_targets = {"ref:plan": set(targets)}
    app.plans_pane = SimpleNamespace(
        _rows={row.row_id: row for row in rows},
        entry_targets=lambda: targets,
    )

    assert app._handle_copy_key("t") is True

    copied, message = app.copies[0]
    assert "### proposal-1\n```\nPlan 1\n```" in copied
    assert "### proposal-2\n```\nPlan 2\n```" in copied
    assert message == "Copied 2 plan titles"


def test_marked_files_contents_report_pre_filtered_binary_rows(
    tmp_path: Path,
) -> None:
    text_path = tmp_path / "notes.md"
    text_path.write_text("# Copy notes", encoding="utf-8")
    text = artifact_file(
        "notes",
        artifact_id="default:111111111111111111111111",
        kind="markdown",
        path=str(text_path),
    )
    image = artifact_file(
        "image",
        artifact_id="default:222222222222222222222222",
        kind="image",
        path=str(tmp_path / "image.png"),
    )
    targets = (("file", text.id), ("file", image.id))
    by_target = dict(zip(targets, (text, image), strict=True))
    app = CopyHarness()
    app.current_artifacts_subtab = "files"
    app._artifacts_marked_targets = {"files": set(targets)}
    app.files_pane = SimpleNamespace(
        entry_targets=lambda: targets,
        entries_for_targets=lambda requested: tuple(
            by_target[target] for target in requested if target in by_target
        ),
        snapshot=SimpleNamespace(
            view_mode_for=lambda entry: (
                "markdown" if entry.kind == "markdown" else "image"
            )
        ),
    )

    assert app._handle_copy_key("percent_sign") is True

    copied, message = app.copies[0]
    assert "### notes artifact\n```" in copied
    assert "# Copy notes" in copied
    assert "image artifact" not in copied
    assert message == "Copied 1 artifact-file contents — 1 entry unavailable"
