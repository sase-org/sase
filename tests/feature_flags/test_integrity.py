"""Registry/bead integrity findings for flag task beads."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sase.feature_flags.integrity import registry_integrity_findings
from sase.feature_flags.orphan import ORPHAN_BEAD_GRACE
from tests.feature_flags._helpers import definitions, demo_flag, flag_bead

_NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)


def test_wrong_type_names_a_non_flag_task_bead() -> None:
    findings = registry_integrity_findings(
        definitions(demo_flag("demo_flag")),
        (flag_bead("demo_flag", task_type="bug"),),
    )

    assert [finding.code for finding in findings] == ["wrong_type"]
    assert "not a `flag` task bead" in findings[0].message


def test_kind_mismatch_when_bead_kind_disagrees() -> None:
    findings = registry_integrity_findings(
        definitions(demo_flag("demo_flag", kind="beta")),
        (flag_bead("demo_flag", kind="sunset"),),
    )

    assert [finding.code for finding in findings] == ["kind_mismatch"]
    assert "kind 'beta'" in findings[0].message
    assert "kind 'sunset'" in findings[0].message


def test_matching_flag_task_bead_is_clean() -> None:
    findings = registry_integrity_findings(
        definitions(demo_flag("demo_flag", kind="beta")),
        (flag_bead("demo_flag", kind="beta"),),
    )

    assert findings == ()


def test_legacy_flag_snapshot_without_kind_skips_kind_check() -> None:
    findings = registry_integrity_findings(
        definitions(demo_flag("demo_flag", kind="beta")),
        (flag_bead("demo_flag"),),
    )

    assert findings == ()


def test_due_state_still_requires_both_thresholds() -> None:
    from sase.feature_flags.integrity import due_integrity_findings

    soon = due_integrity_findings(
        definitions(demo_flag("demo_flag")),
        (flag_bead("demo_flag"),),
        today=date(2026, 12, 15),
        release="0.16.0",
    )
    due = due_integrity_findings(
        definitions(demo_flag("demo_flag")),
        (flag_bead("demo_flag"),),
        today=date(2026, 12, 15),
        release="0.19.0",
    )

    assert [finding.code for finding in soon] == ["soon"]
    assert [finding.code for finding in due] == ["due"]


def test_orphan_bead_errors_when_definition_is_missing() -> None:
    findings = registry_integrity_findings(
        {},
        (flag_bead("ghost_flag", bead_id="sase-orphan"),),
        now=_NOW,
    )

    assert [finding.code for finding in findings] == ["orphan_bead"]
    assert findings[0].severity == "error"
    assert "sase-orphan" in findings[0].message
    assert "ghost_flag" in findings[0].message


def test_orphan_bead_warns_when_checkout_is_older_than_bead() -> None:
    findings = registry_integrity_findings(
        {},
        (
            flag_bead(
                "ghost_flag",
                bead_id="sase-qq",
                created_at="2026-08-19T01:21:12Z",
                created_by="sase-qn.2",
            ),
        ),
        checkout_committed_at=datetime(2026, 8, 18, tzinfo=UTC),
        now=_NOW,
    )

    assert [finding.code for finding in findings] == ["orphan_bead"]
    assert findings[0].severity == "warning"
    assert "older than the bead" in findings[0].message
    assert "sase-qn.2" in findings[0].message


def test_orphan_bead_warns_when_bead_is_within_landing_grace() -> None:
    created = _NOW - (ORPHAN_BEAD_GRACE / 2)
    findings = registry_integrity_findings(
        {},
        (
            flag_bead(
                "ghost_flag",
                bead_id="sase-qq",
                created_at=created.isoformat().replace("+00:00", "Z"),
                created_by="sase-qn.2",
            ),
        ),
        checkout_committed_at=_NOW,
        now=_NOW,
    )

    assert [finding.code for finding in findings] == ["orphan_bead"]
    assert findings[0].severity == "warning"
    assert "may still be landing" in findings[0].message


def test_orphan_bead_errors_when_bead_predates_checkout_and_grace() -> None:
    created = _NOW - ORPHAN_BEAD_GRACE - ORPHAN_BEAD_GRACE
    findings = registry_integrity_findings(
        {},
        (
            flag_bead(
                "ghost_flag",
                bead_id="sase-orphan",
                created_at=created.isoformat().replace("+00:00", "Z"),
                created_by="sase-old",
            ),
        ),
        checkout_committed_at=_NOW,
        now=_NOW,
    )

    assert [finding.code for finding in findings] == ["orphan_bead"]
    assert findings[0].severity == "error"
    assert "add the registry definition" in findings[0].message
    assert "sase-old" in findings[0].message
