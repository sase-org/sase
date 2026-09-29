"""Tests for prediction history rows, tokens, and the project resolver."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.core.prompt_history_filter_wire import PromptHistoryProjectIdentity
from sase.history.prompt_prediction_rows import (
    PromptPredictionProjectResolver,
    build_prompt_prediction_project_resolver,
    build_prompt_prediction_rows,
    normalize_session_text,
    prompt_prediction_source_token,
)
from sase.history.prompt_store import PromptEntry, save_shard
from tests.conftest import redirect_sase_home


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")


def _entry(
    text: str,
    last_used: str = "260101_000000",
    *,
    timestamp: str | None = None,
    origin: str | None = None,
    cancelled: bool = False,
) -> PromptEntry:
    return PromptEntry(
        text=text,
        timestamp=timestamp or last_used,
        last_used=last_used,
        cancelled=cancelled,
        origin=origin,  # type: ignore[arg-type]
    )


def _rows_for(entries: list[PromptEntry], **kwargs):  # type: ignore[no-untyped-def]
    by_path = {}
    paths = []
    for index, entry in enumerate(entries):
        path = Path(f"shard-{index}.json")
        by_path[path] = [entry]
        paths.append(path)
    return build_prompt_prediction_rows(
        shard_limit=None,
        prompt_limit=None,
        shard_paths=paths,
        load_shard_func=lambda path: by_path[path],
        **kwargs,
    )


def test_rows_carry_origin_cancelled_and_project() -> None:
    rows = _rows_for(
        [
            _entry("help me implement the plan", origin="typed"),
            _entry("machine generated review", origin="generated", cancelled=True),
        ],
        resolve_project=lambda text: "sase" if "plan" in text else None,
    )
    by_text = {row.text: row for row in rows}
    assert by_text["help me implement the plan"].origin == "typed"
    assert by_text["help me implement the plan"].project == "sase"
    assert by_text["help me implement the plan"].cancelled is False
    assert by_text["machine generated review"].origin == "generated"
    assert by_text["machine generated review"].cancelled is True
    assert by_text["machine generated review"].project is None


def test_rows_dedup_newest_first_with_typed_wins_merge() -> None:
    rows = _rows_for(
        [
            _entry("same prompt text", last_used="260103_000000"),
            _entry("same prompt text", last_used="260101_000000", origin="typed"),
        ]
    )
    assert [row.text for row in rows] == ["same prompt text"]
    assert rows[0].epoch_seconds > 0
    # Newest epoch wins, typed origin merges up from the older duplicate.
    assert rows[0].origin == "typed"


def test_row_epoch_falls_back_to_timestamp() -> None:
    rows = _rows_for(
        [_entry("fallback epoch", last_used="junk", timestamp="260102_000000")]
    )
    assert rows[0].epoch_seconds > 0
    rows = _rows_for([_entry("zero epoch", last_used="junk", timestamp="junk")])
    assert rows[0].epoch_seconds == 0


def test_source_token_changes_with_new_shard_content(tmp_path: Path) -> None:
    first = tmp_path / "260101.json"
    second = tmp_path / "260102.json"
    assert save_shard(first, [_entry("first prompt here")])
    before = prompt_prediction_source_token(shard_paths=[first])
    assert save_shard(second, [_entry("second prompt here")])
    after = prompt_prediction_source_token(shard_paths=[first, second])
    assert after != before
    assert after[0] != before[0]


def test_source_token_includes_deletions_store(tmp_path: Path) -> None:
    shard = tmp_path / "260101.json"
    assert save_shard(shard, [_entry("first prompt here")])
    from sase.history.prompt_word_deletions import delete_prompt_word

    before = prompt_prediction_source_token(shard_paths=[shard])
    assert delete_prompt_word("obsolete")
    after = prompt_prediction_source_token(shard_paths=[shard])
    assert after != before
    assert after[1] != before[1]
    assert after[0] == before[0]


def test_normalize_session_text_folds_case_and_whitespace() -> None:
    assert normalize_session_text("  Help Me  ") == normalize_session_text("help me")


def _catalog(entries: list[PromptHistoryProjectIdentity]):  # type: ignore[no-untyped-def]
    class _FakeCatalog:
        def __init__(self) -> None:
            self.entries = tuple(entries)

    return _FakeCatalog()


def _resolver() -> PromptPredictionProjectResolver:
    catalog = _catalog(
        [
            PromptHistoryProjectIdentity(
                key="sase",
                label="sase",
                aliases=["s"],
                raw_refs=["bryan/sase"],
            )
        ]
    )
    with patch(
        "sase.history.prompt_history_project_filter.PromptHistoryProjectCatalog.load",
        return_value=catalog,
    ):
        return build_prompt_prediction_project_resolver()


def test_resolver_maps_aliases_and_owner_refs() -> None:
    resolver = _resolver()
    assert resolver.mapping["s"] == "sase"
    assert resolver.mapping["bryan/sase"] == "sase"
    assert resolver.mapping["sase"] == "sase"


def test_resolve_prefers_vcs_tag_and_falls_back_to_lowercase() -> None:
    resolver = _resolver()
    assert resolver.resolve("#gh:sase help me implement this") == "sase"
    assert resolver.resolve("#gh:unknown help me implement this") == "unknown"


def test_resolve_plus_tag_and_skips_inert_zones() -> None:
    resolver = _resolver()
    assert resolver.resolve("help me +s implement this") == "sase"
    assert resolver.resolve("help me +Unknown implement this") == "unknown"
    assert resolver.resolve("fix `+s` in code") is None
    assert resolver.resolve("plain prompt without tags") is None


def test_resolver_build_degrades_to_empty_mapping_on_catalog_failure() -> None:
    with patch(
        "sase.history.prompt_history_project_filter.PromptHistoryProjectCatalog.load",
        side_effect=OSError("disk gone"),
    ):
        resolver = build_prompt_prediction_project_resolver()
    assert resolver.mapping == {}
    assert resolver.resolve("#gh:sase help me") == "sase"
