"""Flag group rows and due metadata for the Artifacts Beads pane."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

from rich.console import Console

from sase.ace.tui.widgets.artifacts.beads_data_models import ProjectBead
from sase.ace.tui.widgets.artifacts.beads_detail import (
    bead_body_markdown,
    bead_preview_markdown,
    bead_properties_header,
)
from sase.ace.tui.widgets.artifacts.beads_list import build_bead_options
from sase.ace.tui.widgets.artifacts.beads_rendering import (
    build_beads_status,
    flag_text,
)
from sase.bead.model import Issue, IssueType
from sase.bead_flag_presentation import flag_due_presentation
from tests.ace.tui._artifacts_beads_helpers import snapshot

__all__ = [
    "test_flag_group_rows_status_and_detail_render_due_metadata",
    "test_flag_task_rows_keep_countdown_and_gain_task_type_chip",
]


def test_flag_group_rows_status_and_detail_render_due_metadata(
    tmp_path: Path,
) -> None:
    flag = Issue(
        "alpha-flag",
        "Remove plugin switch",
        issue_type=IssueType.TASK,
        task_type="flag",
        task_type_fields={
            "key": "plugins_enabled",
            "kind": "beta",
            "when_enabled": "on",
            "when_disabled": "off",
            "remove_when": "done",
            "remove_by_date": "2026-12-01",
            "remove_by_release": "0.19.0",
        },
    )
    due = flag_due_presentation(
        flag.task_type_fields["remove_by_date"],
        flag.task_type_fields["remove_by_release"],
        today=date(2026, 12, 7),
        release="0.19.0",
    )
    value = replace(
        snapshot(tmp_path),
        flags=(ProjectBead("alpha", flag),),
        flag_due={("alpha", flag.id): due},
    )

    options, rows = build_bead_options(
        value,
        project_scope="alpha",
        loading=False,
        expanded_epics=set(),
    )
    prompts = {option.id: option.prompt.plain for option in options if option.id}
    option_ids = [option.id for option in options]
    status = build_beads_status(value, loading=False, load_error=None).plain
    row = flag_text(flag, due=due).plain
    console = Console(width=100, color_system=None)
    with console.capture() as capture:
        console.print(
            bead_properties_header(
                flag,
                value,
                project="alpha",
                project_name="Alpha",
            )
        )
    properties = capture.get()
    body = bead_body_markdown(flag)
    preview = bead_preview_markdown(flag, value, project="alpha")

    assert option_ids.index("header:tasks") < option_ids.index("header:flags")
    assert option_ids.index("header:flags") < option_ids.index("header:epics")
    assert prompts["header:flags"].startswith("── Flags (1)")
    assert rows["flag:alpha-flag"].kind == "flag"
    assert "⚑ alpha-flag Remove plugin switch" in row
    assert "⚑ plugins_enabled" in row
    assert "DUE ⧗ +6d" in row
    assert "2 tasks  ·  1 flag (1 due)  ·  1 epic  ·  2 phases" in status
    assert "Flag" in properties
    assert "plugins_enabled" in properties
    assert "Due state" in properties
    assert "DUE ⧗ +6d" in properties
    assert "## Flag" in body
    assert "- Key: `plugins_enabled`" in body
    assert "**Due state:** due (DUE ⧗ +6d)" in preview


def test_flag_task_rows_keep_countdown_and_gain_task_type_chip(
    tmp_path: Path,
) -> None:
    flag = Issue(
        "alpha-flag",
        "Remove plugin switch",
        issue_type=IssueType.TASK,
        task_type="flag",
        task_type_fields={
            "key": "plugins_enabled",
            "kind": "beta",
            "when_enabled": "new path",
            "when_disabled": "old path",
            "remove_when": "when proven",
            "remove_by_date": "2026-12-01",
            "remove_by_release": "0.19.0",
        },
    )
    due = flag_due_presentation(
        "2026-12-01",
        "0.19.0",
        today=date(2026, 12, 7),
        release="0.19.0",
    )
    value = replace(
        snapshot(tmp_path),
        flags=(ProjectBead("alpha", flag),),
        flag_due={("alpha", flag.id): due},
    )

    options, rows = build_bead_options(
        value,
        project_scope="alpha",
        loading=False,
        expanded_epics=set(),
    )
    prompts = {option.id: option.prompt.plain for option in options if option.id}
    row = flag_text(flag, due=due).plain
    preview = bead_preview_markdown(flag, value, project="alpha")
    body = bead_body_markdown(flag)

    assert rows["flag:alpha-flag"].kind == "flag"
    assert prompts["header:flags"].startswith("── Flags (1)")
    assert "⚑ alpha-flag Remove plugin switch" in row
    assert "⚑ plugins_enabled" in row
    assert "DUE ⧗ +6d" in row
    assert "**Task type:** flag" in preview
    assert "**Flag key:** plugins_enabled" in preview
    assert "## Flag" in body
    assert "- Key: `plugins_enabled`" in body
