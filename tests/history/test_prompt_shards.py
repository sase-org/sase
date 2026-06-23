"""Tests for sharded prompt-history storage and paging."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.history.prompt_catalog import load_prompt_record_page
from sase.history.prompt_store import (
    PromptEntry,
    add_or_update_prompt,
    iter_shard_paths_newest_first,
    load_prompt_history,
    save_prompt_history,
    shard_key_for_timestamp,
    shard_path,
)


def _entry(
    text: str,
    last_used: str,
    *,
    timestamp: str | None = None,
    cancelled: bool = False,
) -> PromptEntry:
    return PromptEntry(
        text=text,
        timestamp=timestamp or last_used,
        last_used=last_used,
        cancelled=cancelled,
    )


def _legacy_data(entries: list[PromptEntry]) -> dict[str, object]:
    return {
        "prompts": [
            {
                "text": entry.text,
                "timestamp": entry.timestamp,
                "last_used": entry.last_used,
                "cancelled": entry.cancelled,
            }
            for entry in entries
        ]
    }


def test_shard_key_for_timestamp_uses_yymm_or_unknown(tmp_path: Path) -> None:
    with patch("sase.history.prompt_store._PROMPT_HISTORY_DIR", tmp_path):
        assert shard_key_for_timestamp("260601_123456") == "2606"
        assert shard_key_for_timestamp("not-a-time") == "unknown"
        assert shard_path("2606") == tmp_path / "2606.json"


def test_write_touches_only_current_month_shard(tmp_path: Path) -> None:
    history_dir = tmp_path / "prompt_history"
    with (
        patch("sase.history.prompt_store._PROMPT_HISTORY_DIR", history_dir),
        patch(
            "sase.history.prompt_store._LEGACY_PROMPT_HISTORY_FILE",
            tmp_path / "prompt_history.json",
        ),
    ):
        save_prompt_history([_entry("old prompt", "260501_000000")])
        old_shard = history_dir / "2605.json"
        before_bytes = old_shard.read_bytes()
        before_mtime = old_shard.stat().st_mtime_ns

        with patch(
            "sase.history.prompt_store.generate_timestamp",
            return_value="260601_120000",
        ):
            add_or_update_prompt("new prompt")

        assert old_shard.read_bytes() == before_bytes
        assert old_shard.stat().st_mtime_ns == before_mtime
        current = json.loads((history_dir / "2606.json").read_text(encoding="utf-8"))
        assert [entry["text"] for entry in current["prompts"]] == ["new prompt"]


def test_cross_month_reuse_appends_current_copy_and_dedups_newest(
    tmp_path: Path,
) -> None:
    history_dir = tmp_path / "prompt_history"
    with (
        patch("sase.history.prompt_store._PROMPT_HISTORY_DIR", history_dir),
        patch(
            "sase.history.prompt_store._LEGACY_PROMPT_HISTORY_FILE",
            tmp_path / "prompt_history.json",
        ),
    ):
        save_prompt_history([_entry("shared prompt", "260501_000000")])

        with patch(
            "sase.history.prompt_store.generate_timestamp",
            return_value="260601_120000",
        ):
            add_or_update_prompt("shared prompt")

        assert len(json.loads((history_dir / "2605.json").read_text())["prompts"]) == 1
        assert len(json.loads((history_dir / "2606.json").read_text())["prompts"]) == 1
        entries = load_prompt_history()
        assert [
            (entry.text, entry.timestamp, entry.last_used) for entry in entries
        ] == [("shared prompt", "260501_000000", "260601_120000")]


def test_cross_month_normal_cancel_newest_wins_but_preserves_prompt(
    tmp_path: Path,
) -> None:
    history_dir = tmp_path / "prompt_history"
    with (
        patch("sase.history.prompt_store._PROMPT_HISTORY_DIR", history_dir),
        patch(
            "sase.history.prompt_store._LEGACY_PROMPT_HISTORY_FILE",
            tmp_path / "prompt_history.json",
        ),
    ):
        save_prompt_history([_entry("shared prompt", "260501_000000")])
        with patch(
            "sase.history.prompt_store.generate_timestamp",
            return_value="260601_120000",
        ):
            add_or_update_prompt("shared prompt", cancelled=True)

        (entry,) = load_prompt_history()
        assert entry.text == "shared prompt"
        assert entry.cancelled is True


def test_legacy_migration_is_loss_free_idempotent_and_keeps_backup(
    tmp_path: Path,
) -> None:
    history_dir = tmp_path / "prompt_history"
    legacy_file = tmp_path / "prompt_history.json"
    legacy_entries = [
        _entry("june prompt", "260601_000000"),
        _entry("may prompt", "260501_000000"),
        _entry("unknown prompt", "not-a-time"),
    ]
    legacy_file.write_text(json.dumps(_legacy_data(legacy_entries)), encoding="utf-8")

    with (
        patch("sase.history.prompt_store._PROMPT_HISTORY_DIR", history_dir),
        patch("sase.history.prompt_store._LEGACY_PROMPT_HISTORY_FILE", legacy_file),
        patch(
            "sase.history.prompt_store.generate_timestamp",
            return_value="260602_030405",
        ),
    ):
        entries = load_prompt_history()
        assert {entry.text for entry in entries} == {
            "june prompt",
            "may prompt",
            "unknown prompt",
        }
        assert legacy_file.exists() is False
        backups = list(history_dir.glob("legacy-imported-260602_030405.json.bak"))
        assert len(backups) == 1
        assert {path.name for path in iter_shard_paths_newest_first()} == {
            "2606.json",
            "2605.json",
            "unknown.json",
        }

        before = {path.name: path.read_text() for path in history_dir.glob("*.json")}
        assert {entry.text for entry in load_prompt_history()} == {
            "june prompt",
            "may prompt",
            "unknown prompt",
        }
        after = {path.name: path.read_text() for path in history_dir.glob("*.json")}
        assert after == before


def test_paged_reader_splits_heavy_month_and_dedups_across_pages(
    tmp_path: Path,
) -> None:
    history_dir = tmp_path / "prompt_history"
    with (
        patch("sase.history.prompt_store._PROMPT_HISTORY_DIR", history_dir),
        patch(
            "sase.history.prompt_store._LEGACY_PROMPT_HISTORY_FILE",
            tmp_path / "prompt_history.json",
        ),
    ):
        entries = [
            _entry("reused prompt", "260601_000001", timestamp="260501_000001"),
            *[_entry(f"new prompt {i}", f"260601_0001{i:02d}") for i in range(5)],
            _entry("reused prompt", "260501_000001"),
        ]
        save_prompt_history(entries)

        first = load_prompt_record_page(page_size=3, include_cancelled=True)
        assert [record.text for record in first.records] == [
            "new prompt 4",
            "new prompt 3",
            "new prompt 2",
        ]
        assert first.exhausted is False
        assert first.next_cursor is not None

        second = load_prompt_record_page(
            page_size=3,
            cursor=first.next_cursor,
            include_cancelled=True,
        )
        assert [record.text for record in second.records] == [
            "new prompt 1",
            "new prompt 0",
            "reused prompt",
        ]
        assert second.exhausted is False
        assert second.next_cursor is not None

        final = load_prompt_record_page(
            page_size=3,
            cursor=second.next_cursor,
            include_cancelled=True,
        )
        assert final.records == []
        assert final.exhausted is True
        assert final.next_cursor is None
