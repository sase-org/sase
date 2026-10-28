"""Tests for Footprint derived-source extractors and history backfill."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sase.footprint.derived import fold_derived_sources
from sase.footprint.derived_auto import extract_auto_rows
from sase.footprint.derived_config import extract_config_rows
from sase.footprint.derived_history import extract_history_rows
from sase.footprint.derived_macros import extract_macro_rows
from sase.footprint.derived_rows import (
    DAILY_ROW_KEYS,
    FORBIDDEN_SOURCE_FIELDS,
    assert_row_allowlist,
)
from sase.footprint.derived_skills import extract_skill_rows
from sase.main.footprint_handler import _handle_backfill
from sase.main.parser import create_parser


def _assert_private(rows: list[dict[str, object]]) -> None:
    assert_row_allowlist(rows)
    for row in rows:
        assert set(row) <= DAILY_ROW_KEYS
        assert FORBIDDEN_SOURCE_FIELDS.isdisjoint(row)


def test_macro_extractor_splits_parent_actor_and_collapses_custom_names() -> None:
    payload = {
        "schema_version": 1,
        "rows": [
            {"ts": 1_783_645_200, "name": "research", "has_parent": False, "n": 2},
            {"ts": 1_783_645_200, "name": "user-macro", "has_parent": True, "n": 1},
            {"ts": "not-a-timestamp", "name": "research", "has_parent": False, "n": 1},
        ],
    }

    days, rows, coverage = extract_macro_rows(
        catalog_ids={"macro:research"},
        today="2026-07-10",
        query=lambda **_kwargs: payload,
    )

    _assert_private(rows)
    by_id = {(row["feature_id"], row["actor"]): row for row in rows}
    assert by_id[("macro:research", "human")]["n"] == 2
    assert by_id[("macro:~custom", "agent")]["n"] == 1
    assert "2026-07-10" in days
    assert coverage[0]["surface"] == "macro"


def test_skill_extractor_reads_only_name_and_day(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "skill_uses.jsonl").write_text(
        json.dumps(
            {
                "skill_name": "sase_repo",
                "timestamp": "2026-10-20T12:00:00Z",
                "agent_name": "secret-agent",
                "cwd": "/secret/path",
                "project": "secret-project",
                "reason": "do not copy",
            }
        )
        + "\n"
        + json.dumps(
            {
                "skill_name": "custom-skill",
                "timestamp": "2026-10-20T13:00:00Z",
                "prompt": "secret prompt",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    days, rows, coverage = extract_skill_rows(
        catalog_ids={"skill:sase_repo"},
        today="2026-10-27",
        projects_dir=tmp_path,
    )

    _assert_private(rows)
    by_id = {row["feature_id"]: row for row in rows}
    assert by_id["skill:sase_repo"]["n"] == 1
    assert by_id["skill:sase_repo"]["actor"] == "agent"
    assert by_id["skill:~custom"]["n"] == 1
    assert "2026-10-20" in days
    assert coverage[0]["human_active"] == 0
    dumped = json.dumps(rows)
    assert "secret-agent" not in dumped
    assert "/secret/path" not in dumped
    assert "secret-project" not in dumped
    assert "secret prompt" not in dumped


def test_config_extractor_records_paths_never_values(tmp_path: Path) -> None:
    (tmp_path / "sase.yml").write_text(
        "ace:\n  page_size: SUPER_SECRET_VALUE\nunknown_leaf: also-secret\n",
        encoding="utf-8",
    )

    days, rows, coverage = extract_config_rows(
        catalog_ids={"config:ace.page_size"},
        today="2026-10-27",
        config_dir=tmp_path,
    )

    _assert_private(rows)
    by_id = {row["feature_id"]: row for row in rows}
    assert by_id["config:ace.page_size"]["n"] == 1
    assert by_id["config:ace.page_size"]["via"] == "config"
    assert by_id["config:~custom"]["n"] == 1
    assert days == ["2026-10-27"]
    dumped = json.dumps(rows)
    assert "SUPER_SECRET_VALUE" not in dumped
    assert "also-secret" not in dumped
    assert "unknown_leaf" not in dumped
    assert coverage[0]["human_active"] == 1


def test_auto_extractor_maps_known_routines_and_skips_unknown_labels() -> None:
    payload = {
        "series": [
            {
                "labels": {"cycle_type": "housekeeping"},
                "points": [{"ts": 1_783_645_200, "value": 4}],
            },
            {
                "labels": {"cycle_type": "not-a-catalog-routine"},
                "points": [{"ts": 1_783_645_200, "value": 9}],
            },
            {
                "labels": {},
                "points": [{"ts": 1_783_645_200, "value": 3}],
            },
        ]
    }

    _days, rows, coverage = extract_auto_rows(
        catalog_ids={"auto:axe.housekeeping"},
        today="2026-07-10",
        query=lambda *_args, **_kwargs: payload,
    )

    _assert_private(rows)
    assert [row["feature_id"] for row in rows] == ["auto:axe.housekeeping"]
    assert rows[0]["n"] == 4
    assert rows[0]["actor"] == "automation"
    assert "not-a-catalog-routine" not in json.dumps(rows)
    assert coverage[0]["surface"] == "auto"


def test_history_extractor_keeps_ids_and_skips_untimestamped(tmp_path: Path) -> None:
    history = tmp_path / "zsh_history"
    history.write_text(
        ": 1783645200:1;sase bead list --format json\n"
        ": 1783645300:0;echo secret-command\n"
        "sase footprint status\n"
        ": 1783645400:0;sase listen\n",
        encoding="utf-8",
    )
    parser = create_parser()

    preview = extract_history_rows(history, parser=parser, today="2026-07-10")

    _assert_private(list(preview.rows))
    dumped = json.dumps(preview.rows)
    assert "secret-command" not in dumped
    assert "echo" not in dumped
    assert preview.skipped_untimestamped == 1
    assert preview.commands["cli:bead.list"] == 1
    assert preview.commands["plugin:listen"] == 1
    option_ids = {row["feature_id"] for row in preview.rows if "#" in row["feature_id"]}
    assert any(item.endswith("#format") for item in option_ids)


def test_fold_derived_sources_keeps_previous_origin_on_failure(
    monkeypatch, tmp_path: Path
) -> None:
    calls: list[str] = []

    def boom(**_kwargs):
        raise RuntimeError("macros failed")

    def skills(**_kwargs):
        return (
            ["2026-10-27"],
            [
                {
                    "day": "2026-10-27",
                    "feature_id": "skill:sase_repo",
                    "actor": "agent",
                    "via": "prompt",
                    "outcome": "ok",
                    "n": 1,
                    "dur_ms_sum": 0,
                    "dur_ms_max": 0,
                }
            ],
            [
                {
                    "day": "2026-10-27",
                    "surface": "skill",
                    "measured": 1,
                    "human_active": 0,
                    "records": 1,
                    "torn": 0,
                    "dropped": 0,
                    "unknown_ids": 0,
                    "incomplete": 0,
                }
            ],
        )

    monkeypatch.setattr("sase.footprint.derived.extract_macro_rows", boom)
    monkeypatch.setattr("sase.footprint.derived.extract_skill_rows", skills)
    monkeypatch.setattr(
        "sase.footprint.derived.extract_config_rows",
        lambda **_kwargs: (["2026-10-27"], [], []),
    )
    monkeypatch.setattr(
        "sase.footprint.derived.extract_auto_rows",
        lambda **_kwargs: (["2026-10-27"], [], []),
    )

    def upsert(_store, origin, _days, _rows, _coverage, **_kwargs) -> None:
        calls.append(origin)

    monkeypatch.setattr("sase.footprint.derived.footprint_upsert_derived", upsert)
    monkeypatch.setattr(
        "sase.footprint.derived.footprint_ledger_path",
        lambda _home: tmp_path / "footprint.sqlite",
    )

    result = fold_derived_sources(
        sase_home=tmp_path, today="2026-10-27", catalog_ids=set()
    )

    assert result["derived.macros"]["ok"] is False
    assert result["derived.skills"]["ok"] is True
    assert "derived.macros" not in calls
    assert "derived.skills" in calls


def test_backfill_requires_confirmation_without_yes(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    history = tmp_path / "zsh_history"
    history.write_text(": 1783645200:0;sase version\n", encoding="utf-8")

    class NonInteractive:
        def isatty(self) -> bool:
            return False

    monkeypatch.setattr("sys.stdin", NonInteractive())
    args = argparse.Namespace(path=str(history), yes=False)

    assert _handle_backfill(args) == 2
    assert "sase footprint backfill -y" in capsys.readouterr().err
