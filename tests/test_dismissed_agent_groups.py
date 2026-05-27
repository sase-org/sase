"""Tests for saved dismissed-agent group persistence."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.ace.dismissed_agents import (
    list_dismissed_agent_groups,
    load_dismissed_agent_group,
    mark_dismissed_agent_group_revived,
    save_dismissed_agent_group,
)
from sase.core.agent_group_archive_wire import (
    SavedAgentGroupRefWire,
    SavedAgentGroupWire,
)


def test_saved_agent_group_facade_round_trip(tmp_path: Path) -> None:
    """Saved groups persist summary fields and stable bundle refs."""

    groups_dir = tmp_path / "groups"
    missing_bundle = tmp_path / "missing-bundle.json"
    group = _group(
        "group-a",
        "2026-05-27T12:00:00Z",
        bundle_path=str(missing_bundle),
    )

    with patch("sase.ace.dismissed_agents._DISMISSED_AGENT_GROUPS_DIR", groups_dir):
        saved = save_dismissed_agent_group(group)
        page = list_dismissed_agent_groups(limit=20)
        loaded = load_dismissed_agent_group("group-a")

    assert saved.group_id == "group-a"
    assert (groups_dir / "group-a.json").is_file()
    assert [summary.group_id for summary in page.groups] == ["group-a"]
    assert loaded is not None
    assert loaded.agent_refs[0].bundle_path == str(missing_bundle)
    assert not missing_bundle.exists()


def test_saved_agent_group_pages_are_newest_first(tmp_path: Path) -> None:
    """List pages use deterministic newest-first offset cursors."""

    groups_dir = tmp_path / "groups"
    with patch("sase.ace.dismissed_agents._DISMISSED_AGENT_GROUPS_DIR", groups_dir):
        for idx in range(22):
            save_dismissed_agent_group(
                _group(f"group-{idx:02}", f"2026-05-27T12:{idx:02}:00Z")
            )

        first = list_dismissed_agent_groups(limit=20)
        second = list_dismissed_agent_groups(limit=20, cursor=first.next_cursor)

    assert [summary.group_id for summary in first.groups[:2]] == [
        "group-21",
        "group-20",
    ]
    assert first.next_cursor == 20
    assert [summary.group_id for summary in second.groups] == [
        "group-01",
        "group-00",
    ]
    assert second.next_cursor is None


def test_saved_agent_group_corrupt_missing_and_revived_marking(
    tmp_path: Path,
) -> None:
    """Corrupt group files are skipped and revival marking preserves refs."""

    groups_dir = tmp_path / "groups"
    groups_dir.mkdir()
    (groups_dir / "corrupt.json").write_text("not json", encoding="utf-8")

    with patch("sase.ace.dismissed_agents._DISMISSED_AGENT_GROUPS_DIR", groups_dir):
        save_dismissed_agent_group(_group("valid", "2026-05-27T12:00:00Z"))
        page = list_dismissed_agent_groups(limit=20)
        missing = load_dismissed_agent_group("missing")
        corrupt = load_dismissed_agent_group("corrupt")
        revived = mark_dismissed_agent_group_revived(
            "valid",
            revived_at="2026-05-27T13:00:00Z",
        )
        loaded = load_dismissed_agent_group("valid")

    assert [summary.group_id for summary in page.groups] == ["valid"]
    assert missing is None
    assert corrupt is None
    assert revived is not None
    assert revived.revived_at == "2026-05-27T13:00:00Z"
    assert revived.times_revived == 1
    assert loaded is not None
    assert loaded.agent_refs[0].raw_suffix == "ts-1"
    payload = json.loads((groups_dir / "valid.json").read_text(encoding="utf-8"))
    assert payload["title"] == "1 agent in cl"
    assert payload["agent_refs"][0]["raw_suffix"] == "ts-1"


def test_saved_agent_group_python_fallback_when_binding_missing(
    tmp_path: Path,
) -> None:
    """Facade remains usable with stale editable installs."""

    groups_dir = tmp_path / "groups"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_AGENT_GROUPS_DIR", groups_dir),
        patch(
            "sase.ace.dismissed_agent_groups.require_rust_binding",
            side_effect=AttributeError("stale"),
        ),
    ):
        save_dismissed_agent_group(_group("fallback", "2026-05-27T12:00:00Z"))
        page = list_dismissed_agent_groups(limit=20)

    assert [summary.group_id for summary in page.groups] == ["fallback"]


def _group(
    group_id: str,
    created_at: str,
    *,
    bundle_path: str | None = None,
) -> SavedAgentGroupWire:
    return SavedAgentGroupWire(
        group_id=group_id,
        created_at=created_at,
        source="marked_agents",
        title="1 agent in cl",
        agent_count=1,
        top_level_agent_count=1,
        status_counts={"DONE": 1},
        project_names=("proj",),
        cl_names=("cl",),
        agent_refs=(
            SavedAgentGroupRefWire(
                agent_type="run",
                cl_name="cl",
                raw_suffix="ts-1",
                bundle_path=bundle_path,
                display_name="agent",
                agent_name="agent",
                status="DONE",
                start_time="2026-05-27T11:00:00Z",
                model="gpt",
                llm_provider="codex",
            ),
        ),
    )
