"""Bead-status rules (6-9) for ``tools/check_feature_flags``."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from sase.feature_flags.orphan import ORPHAN_BEAD_GRACE

from tests._check_feature_flags_tool_helpers import (
    _bead,
    _broken_flag,
    _load_tool,
    _restore_sys_path,
    _rules,
)
from tests.feature_flags._helpers import definitions, demo_flag


# Re-imported so pytest collects the autouse sys.path restore from the helper.
pytestmark = pytest.mark.usefixtures("_restore_sys_path")


def test_rule_6_rejects_missing_wrong_type_and_key_mismatch() -> None:
    tool = _load_tool()
    markers = tool.markers_from_flag_definitions(
        definitions(
            _broken_flag("missing_flag", bead="sase-nb.missing"),
            _broken_flag("wrong_type", bead="sase-nb.task"),
            _broken_flag("wrong_key", bead="sase-nb.key"),
        )
    )
    beads = [
        _bead(
            tool,
            bead_id="sase-nb.task",
            key="wrong_type",
            issue_type="task",
            task_type="",
        ),
        _bead(tool, bead_id="sase-nb.key", key="other_key"),
    ]

    findings = tool.check_bead_status(
        markers,
        beads,
        today=date(2026, 1, 1),
        release="0.10.0",
    )

    assert 6 in _rules(findings)
    messages = " ".join(finding.message for finding in findings if finding.rule == 6)
    assert "missing bead" in messages
    assert "not a `flag` task bead" in messages
    assert "whose key is 'other_key'" in messages


def test_rule_6_accepts_flag_task_bead() -> None:
    tool = _load_tool()
    markers = tool.markers_from_flag_definitions(definitions(demo_flag("demo_flag")))

    assert (
        tool.check_bead_status(
            markers,
            [
                _bead(
                    tool,
                    issue_type="task",
                    task_type="flag",
                    kind="beta",
                )
            ],
            today=date(2026, 1, 1),
            release="0.10.0",
        )
        == []
    )


def test_rule_6_rejects_kind_mismatch() -> None:
    tool = _load_tool()
    markers = tool.markers_from_flag_definitions(definitions(demo_flag("demo_flag")))

    findings = tool.check_bead_status(
        markers,
        [
            _bead(
                tool,
                issue_type="task",
                task_type="flag",
                kind="sunset",
            )
        ],
        today=date(2026, 1, 1),
        release="0.10.0",
    )

    assert 6 in _rules(findings)
    assert "kind is 'sunset'" in findings[0].message


def test_rule_6_accepts_matching_flag_bead() -> None:
    tool = _load_tool()
    markers = tool.markers_from_flag_definitions(definitions(demo_flag("demo_flag")))

    assert (
        tool.check_bead_status(
            markers,
            [_bead(tool)],
            today=date(2026, 1, 1),
            release="0.10.0",
        )
        == []
    )


def test_rule_7_rejects_closed_bead_with_surviving_definition() -> None:
    tool = _load_tool()
    markers = tool.markers_from_flag_definitions(definitions(demo_flag("demo_flag")))

    findings = tool.check_bead_status(
        markers,
        [_bead(tool, status="closed")],
        today=date(2026, 1, 1),
        release="0.10.0",
    )

    assert _rules(findings) == [7]
    assert "closed" in findings[0].message
    assert "demo_flag" in findings[0].message


def test_rule_7_accepts_live_bead_with_definition() -> None:
    tool = _load_tool()
    markers = tool.markers_from_flag_definitions(definitions(demo_flag("demo_flag")))

    assert (
        tool.check_bead_status(
            markers,
            [_bead(tool, status="in_progress")],
            today=date(2026, 1, 1),
            release="0.10.0",
        )
        == []
    )


def test_rule_8_rejects_live_orphan_flag_bead() -> None:
    tool = _load_tool()

    findings = tool.check_bead_status(
        (),
        [_bead(tool, bead_id="sase-orphan", key="ghost_flag")],
        today=date(2026, 1, 1),
        release="0.10.0",
    )

    assert _rules(findings) == [8]
    assert "sase-orphan" in findings[0].message
    assert "ghost_flag" in findings[0].message


def test_rule_8_warns_when_bead_is_newer_than_checkout() -> None:
    tool = _load_tool()
    now = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)

    findings = tool.check_bead_status(
        (),
        [
            _bead(
                tool,
                bead_id="sase-qq",
                key="plugin_catalog_scoped_latest",
                created_at="2026-08-19T01:21:12Z",
                created_by="sase-qn.2",
            )
        ],
        today=date(2026, 8, 19),
        release="0.10.0",
        now=now,
        checkout_committed_at=datetime(2026, 8, 18, tzinfo=UTC),
    )

    assert _rules(findings) == [8]
    assert findings[0].severity == "warning"
    assert "sase-qq" in findings[0].message
    assert "older than the bead" in findings[0].message
    assert "sase-qn.2" in findings[0].message


def test_rule_8_warns_when_bead_is_within_landing_grace() -> None:
    tool = _load_tool()
    now = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    created = now - (ORPHAN_BEAD_GRACE / 2)

    findings = tool.check_bead_status(
        (),
        [
            _bead(
                tool,
                bead_id="sase-qq",
                key="plugin_catalog_scoped_latest",
                created_at=created.isoformat().replace("+00:00", "Z"),
                created_by="sase-qn.2",
            )
        ],
        today=date(2026, 8, 19),
        release="0.10.0",
        now=now,
        checkout_committed_at=now,
    )

    assert _rules(findings) == [8]
    assert findings[0].severity == "warning"
    assert "may still be landing" in findings[0].message


def test_rule_8_errors_when_bead_predates_checkout_and_grace() -> None:
    tool = _load_tool()
    now = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    created = now - (ORPHAN_BEAD_GRACE * 2)

    findings = tool.check_bead_status(
        (),
        [
            _bead(
                tool,
                bead_id="sase-orphan",
                key="ghost_flag",
                created_at=created.isoformat().replace("+00:00", "Z"),
                created_by="sase-old",
            )
        ],
        today=date(2026, 8, 19),
        release="0.10.0",
        now=now,
        checkout_committed_at=now,
    )

    assert _rules(findings) == [8]
    assert findings[0].severity == "error"
    assert "add the registry definition" in findings[0].message


def test_rule_8_accepts_closed_orphan_and_defined_live_bead() -> None:
    tool = _load_tool()
    markers = tool.markers_from_flag_definitions(definitions(demo_flag("demo_flag")))

    assert (
        tool.check_bead_status(
            markers,
            [
                _bead(tool),
                _bead(tool, bead_id="sase-old", key="retired_flag", status="closed"),
            ],
            today=date(2026, 1, 1),
            release="0.10.0",
        )
        == []
    )


def test_rule_9_warns_when_overdue_and_never_errors() -> None:
    tool = _load_tool()
    markers = tool.markers_from_flag_definitions(definitions(demo_flag("demo_flag")))

    findings = tool.check_bead_status(
        markers,
        [_bead(tool)],
        today=date(2026, 12, 2),
        release="0.19.0",
    )

    assert len(findings) == 1
    assert findings[0].rule == 9
    assert findings[0].severity == "warning"
    assert "overdue" in findings[0].message


def test_rule_9_is_silent_when_live_or_soon() -> None:
    tool = _load_tool()
    markers = tool.markers_from_flag_definitions(definitions(demo_flag("demo_flag")))

    assert (
        tool.check_bead_status(
            markers,
            [_bead(tool)],
            today=date(2026, 12, 2),
            release="0.10.0",
        )
        == []
    )
    assert (
        tool.check_bead_status(
            markers,
            [_bead(tool)],
            today=date(2026, 1, 1),
            release="0.19.0",
        )
        == []
    )


def test_second_marker_source_reuses_bead_status_rules() -> None:
    tool = _load_tool()
    markers = [
        tool.MarkerDefinition(
            source="backcompat",
            key="old_api",
            kind="sunset",
            bead="sase-bc.1",
        )
    ]
    beads = [
        _bead(
            tool,
            bead_id="sase-bc.1",
            key="old_api",
            issue_type="task",
            status="closed",
            source="backcompat",
        )
    ]

    findings = tool.check_bead_status(
        markers,
        beads,
        today=date(2026, 1, 1),
        release="0.10.0",
        expected_bead_type="task",
    )

    assert _rules(findings) == [7]
    assert "backcompat" in findings[0].message


def test_marker_bead_from_issue_dict_reads_task_type_fields() -> None:
    tool = _load_tool()

    bead = tool.marker_bead_from_issue_dict(
        {
            "id": "sase-xy",
            "status": "open",
            "issue_type": "task",
            "task_type": "flag",
            "task_type_fields": {
                "key": "demo_key",
                "kind": "sunset",
                "remove_by_date": "2026-12-01",
                "remove_by_release": "0.19.0",
            },
        },
        source="flag",
    )

    assert bead.key == "demo_key"
    assert bead.kind == "sunset"
    assert bead.task_type == "flag"
    assert bead.remove_by_date == "2026-12-01"
    assert bead.issue_type == "task"


def test_marker_bead_from_issue_dict_reads_created_at_and_created_by() -> None:
    tool = _load_tool()

    bead = tool.marker_bead_from_issue_dict(
        {
            "id": "sase-qq",
            "status": "open",
            "issue_type": "task",
            "task_type": "flag",
            "created_at": "2026-08-19T01:21:12Z",
            "created_by": "sase-qn.2",
            "task_type_fields": {"key": "plugin_catalog_scoped_latest"},
        },
        source="flag",
    )

    assert bead.created_at == "2026-08-19T01:21:12Z"
    assert bead.created_by == "sase-qn.2"
