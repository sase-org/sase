"""Regression tests for agent bead metadata lookup."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.agent.bead_display import format_agent_bead_display_for_name


def test_agent_bead_display_finds_description_in_legacy_sibling_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = tmp_path / "sase"
    sibling = tmp_path / "sase_106"
    primary.mkdir()
    legacy_store = sibling / ".sase_beads"
    legacy_store.mkdir(parents=True)
    _write_issues(
        legacy_store,
        [
            _issue(
                "sase-99",
                "Legacy epic",
                "2026-05-02T00:00:00Z",
                description="Only present in the migrated legacy store",
            )
        ],
    )

    monkeypatch.setattr(
        "sase.bead.workspace.resolve_primary_workspace",
        lambda: primary,
    )

    assert (
        format_agent_bead_display_for_name("sase-99")
        == "sase-99 - Only present in the migrated legacy store"
    )


def _write_issues(beads_dir: Path, issues: list[dict[str, object]]) -> None:
    text = "".join(json.dumps(issue, separators=(",", ":")) + "\n" for issue in issues)
    (beads_dir / "issues.jsonl").write_text(text, encoding="utf-8")


def _issue(
    issue_id: str,
    title: str,
    updated_at: str,
    *,
    description: str = "",
) -> dict[str, object]:
    return {
        "id": issue_id,
        "title": title,
        "status": "open",
        "issue_type": "plan",
        "parent_id": None,
        "owner": "",
        "assignee": "",
        "created_at": updated_at,
        "created_by": "",
        "updated_at": updated_at,
        "closed_at": None,
        "close_reason": None,
        "description": description,
        "notes": "",
        "design": "",
        "is_ready_to_work": False,
        "changespec_name": "",
        "changespec_bug_id": "",
        "dependencies": [],
    }
