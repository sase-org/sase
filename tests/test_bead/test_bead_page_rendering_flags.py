"""Flag metadata rendering on generated bead pages."""

from __future__ import annotations

from types import MappingProxyType
from typing import cast

from sase.bead.model import Issue, IssueType
from sase.bead.project import BeadProject
from sase.bead_pages.associations import BeadAssociationIndex
from sase.bead_pages.rendering import render_bead_page
from tests.test_bead.bead_page_rendering_test_helpers import View


def test_flag_task_bead_page_reads_task_type_fields() -> None:
    flag = Issue(
        "sase-flag",
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

    rendered = render_bead_page(
        cast(BeadProject, View((flag,))),
        flag,
        BeadAssociationIndex(MappingProxyType({})),
    )

    assert "**Type:** ◆ task" in rendered
    assert "**Task type:** ⚑ flag" in rendered
    assert "**Flag:** ⚑ `plugins_enabled`" in rendered
    assert "## Flag" in rendered
    assert "- **Key:** `plugins_enabled`" in rendered
    assert "- **Remove by date:** `2026-12-01`" in rendered
    assert "- **Remove by release:** `v0.19.0`" in rendered
