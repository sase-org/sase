"""Registry/bead integrity findings for flag task beads."""

from __future__ import annotations

from datetime import date

from sase.feature_flags.integrity import registry_integrity_findings
from tests.feature_flags._helpers import definitions, demo_flag, flag_bead


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
