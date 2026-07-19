"""Tests for saved dismissed-agent group persistence."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.ace.dismissed_agents import (
    delete_dismissed_agent_group,
    list_dismissed_agent_groups,
    list_recent_dismissed_agent_groups,
    load_dismissed_agent_group,
    load_recent_dismissed_agent_group,
    mark_dismissed_agent_group_revived,
    mark_recent_dismissed_agent_group_revived,
    record_recent_dismissed_agent_group,
    save_dismissed_agent_group,
)
from sase.core.agent_group_archive_wire import (
    AGENT_GROUP_ARCHIVE_WIRE_SCHEMA_VERSION,
    SavedAgentGroupRefWire,
    SavedAgentGroupWire,
    saved_agent_group_wire_to_json_dict,
)


def test_saved_agent_group_facade_round_trip(tmp_path: Path) -> None:
    """Saved groups persist summary fields and stable bundle refs."""

    groups_dir = tmp_path / "groups"
    missing_bundle = tmp_path / "missing-bundle.json"
    group = _group(
        "group-a",
        "2026-05-27T12:00:00Z",
        bundle_path=str(missing_bundle),
        name="Backend batch",
    )

    with patch("sase.ace.dismissed_agents._DISMISSED_AGENT_GROUPS_DIR", groups_dir):
        saved = save_dismissed_agent_group(group)
        page = list_dismissed_agent_groups(limit=20)
        loaded = load_dismissed_agent_group("group-a")

    assert saved.group_id == "group-a"
    assert saved.name == "Backend batch"
    assert (groups_dir / "group-a.json").is_file()
    assert [summary.group_id for summary in page.groups] == ["group-a"]
    assert page.groups[0].name == "Backend batch"
    assert loaded is not None
    assert loaded.name == "Backend batch"
    assert loaded.agent_refs[0].bundle_path == str(missing_bundle)
    assert loaded.agent_refs[0].tribe == "backend"
    assert loaded.agent_refs[0].prompt_preview == "Restore this backend worker."
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
    assert payload["agent_refs"][0]["tribe"] == "backend"
    assert "tag" not in payload["agent_refs"][0]


def test_delete_saved_agent_group_removes_group_record(tmp_path: Path) -> None:
    """Deleting a saved group removes only that group metadata file."""

    groups_dir = tmp_path / "groups"
    with patch("sase.ace.dismissed_agents._DISMISSED_AGENT_GROUPS_DIR", groups_dir):
        save_dismissed_agent_group(_group("group-a", "2026-05-27T12:00:00Z"))
        save_dismissed_agent_group(_group("group-b", "2026-05-27T12:01:00Z"))

        deleted = delete_dismissed_agent_group("group-a")
        missing = delete_dismissed_agent_group("group-a")
        page = list_dismissed_agent_groups(limit=20)

    assert deleted is True
    assert missing is False
    assert not (groups_dir / "group-a.json").exists()
    assert (groups_dir / "group-b.json").is_file()
    assert [summary.group_id for summary in page.groups] == ["group-b"]


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
        saved = save_dismissed_agent_group(
            _group("fallback", "2026-05-27T12:00:00Z", name="   ")
        )
        page = list_dismissed_agent_groups(limit=20)

    assert saved.name is None
    assert [summary.group_id for summary in page.groups] == ["fallback"]
    assert page.groups[0].name is None


def test_delete_saved_agent_group_python_fallback_when_binding_missing(
    tmp_path: Path,
) -> None:
    """Delete keeps working when the installed Rust extension is stale."""

    groups_dir = tmp_path / "groups"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_AGENT_GROUPS_DIR", groups_dir),
        patch(
            "sase.ace.dismissed_agent_groups.require_rust_binding",
            side_effect=AttributeError("stale"),
        ),
    ):
        save_dismissed_agent_group(_group("fallback", "2026-05-27T12:00:00Z"))
        deleted = delete_dismissed_agent_group("fallback")
        missing = delete_dismissed_agent_group("fallback")
        page = list_dismissed_agent_groups(limit=20)

    assert deleted is True
    assert missing is False
    assert not (groups_dir / "fallback.json").exists()
    assert page.groups == ()


def test_saved_agent_group_missing_optional_fields_load_as_none(
    tmp_path: Path,
) -> None:
    """Legacy saved-group records without optional fields remain readable."""

    groups_dir = tmp_path / "groups"
    groups_dir.mkdir()
    payload = saved_agent_group_wire_to_json_dict(
        _group("legacy", "2026-05-27T12:00:00Z")
    )
    payload.pop("name", None)
    payload["agent_refs"][0].pop("prompt_preview", None)
    (groups_dir / "legacy.json").write_text(json.dumps(payload), encoding="utf-8")

    with patch("sase.ace.dismissed_agents._DISMISSED_AGENT_GROUPS_DIR", groups_dir):
        loaded = load_dismissed_agent_group("legacy")
        page = list_dismissed_agent_groups(limit=20)

    assert loaded is not None
    assert loaded.name is None
    assert loaded.agent_refs[0].prompt_preview is None
    assert page.groups[0].name is None


def test_version_one_tag_record_loads_and_rewrites_canonically(
    tmp_path: Path,
) -> None:
    groups_dir = tmp_path / "groups"
    groups_dir.mkdir()
    payload = saved_agent_group_wire_to_json_dict(
        _group("legacy-v1", "2026-05-27T12:00:00Z")
    )
    payload["schema_version"] = 1
    ref = payload["agent_refs"][0]
    ref["tag"] = ref.pop("tribe")
    group_path = groups_dir / "legacy-v1.json"
    group_path.write_text(json.dumps(payload), encoding="utf-8")

    with (
        patch("sase.ace.dismissed_agents._DISMISSED_AGENT_GROUPS_DIR", groups_dir),
        patch(
            "sase.ace.dismissed_agent_groups.require_rust_binding",
            side_effect=AttributeError("exercise Python migration"),
        ),
    ):
        loaded = load_dismissed_agent_group("legacy-v1")
        rewritten = mark_dismissed_agent_group_revived(
            "legacy-v1", revived_at="2026-05-27T13:00:00Z"
        )

    assert loaded is not None
    assert loaded.schema_version == AGENT_GROUP_ARCHIVE_WIRE_SCHEMA_VERSION
    assert loaded.agent_refs[0].tribe == "backend"
    assert rewritten is not None
    persisted = json.loads(group_path.read_text())
    assert persisted["schema_version"] == AGENT_GROUP_ARCHIVE_WIRE_SCHEMA_VERSION
    assert persisted["agent_refs"][0]["tribe"] == "backend"
    assert "tag" not in persisted["agent_refs"][0]


def test_recent_dismissed_agent_groups_are_capped_newest_first(
    tmp_path: Path,
) -> None:
    recent_dir = tmp_path / "recent"

    with patch(
        "sase.ace.dismissed_agents._RECENT_DISMISSED_AGENT_GROUPS_DIR", recent_dir
    ):
        for idx in range(12):
            group = _group(
                f"recent-{idx:02}",
                f"2026-05-27T12:{idx:02}:00Z",
            )
            record_recent_dismissed_agent_group(group)

        page = list_recent_dismissed_agent_groups(limit=10)

    assert [summary.group_id for summary in page.groups] == [
        "recent-11",
        "recent-10",
        "recent-09",
        "recent-08",
        "recent-07",
        "recent-06",
        "recent-05",
        "recent-04",
        "recent-03",
        "recent-02",
    ]
    assert page.next_cursor is None
    assert not (recent_dir / "recent-00.json").exists()
    assert not (recent_dir / "recent-01.json").exists()


def test_recent_dismissed_agent_groups_replace_and_mark_revived(
    tmp_path: Path,
) -> None:
    recent_dir = tmp_path / "recent"

    with patch(
        "sase.ace.dismissed_agents._RECENT_DISMISSED_AGENT_GROUPS_DIR", recent_dir
    ):
        record_recent_dismissed_agent_group(
            _group("recent-same", "2026-05-27T12:00:00Z")
        )
        record_recent_dismissed_agent_group(
            _group("recent-same", "2026-05-27T12:30:00Z")
        )
        loaded = load_recent_dismissed_agent_group("recent-same")
        revived = mark_recent_dismissed_agent_group_revived(
            "recent-same",
            revived_at="2026-05-27T13:00:00Z",
        )
        page = list_recent_dismissed_agent_groups(limit=10)

    assert loaded is not None
    assert loaded.created_at == "2026-05-27T12:30:00Z"
    assert revived is not None
    assert revived.revived_at == "2026-05-27T13:00:00Z"
    assert revived.times_revived == 1
    assert [summary.group_id for summary in page.groups] == ["recent-same"]


def test_recent_dismissed_agent_group_python_fallback_tolerates_corrupt(
    tmp_path: Path,
) -> None:
    recent_dir = tmp_path / "recent"
    recent_dir.mkdir()
    (recent_dir / "corrupt.json").write_text("not json", encoding="utf-8")

    with (
        patch(
            "sase.ace.dismissed_agents._RECENT_DISMISSED_AGENT_GROUPS_DIR", recent_dir
        ),
        patch(
            "sase.ace.dismissed_agent_groups.require_rust_binding",
            side_effect=AttributeError("stale"),
        ),
    ):
        record_recent_dismissed_agent_group(
            _group("recent-valid", "2026-05-27T12:00:00Z")
        )
        page = list_recent_dismissed_agent_groups(limit=10)
        corrupt = load_recent_dismissed_agent_group("corrupt")

    assert [summary.group_id for summary in page.groups] == ["recent-valid"]
    assert corrupt is None


def _group(
    group_id: str,
    created_at: str,
    *,
    bundle_path: str | None = None,
    name: str | None = None,
    prompt_preview: str | None = "Restore this backend worker.",
) -> SavedAgentGroupWire:
    return SavedAgentGroupWire(
        group_id=group_id,
        created_at=created_at,
        source="marked_agents",
        title="1 agent in cl",
        name=name,
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
                tribe="backend",
                prompt_preview=prompt_preview,
            ),
        ),
    )
