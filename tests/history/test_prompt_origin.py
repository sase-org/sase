"""Tests for the prompt-history origin (typed vs generated) marker."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.history.prompt_store import (
    PromptEntry,
    PromptOrigin,
    add_or_update_prompt,
    dedup_prompt_entries_newest_first,
    load_prompt_history,
    prompt_entry_from_json,
    record_failed_launch_prompt,
    rewrite_prompt_text_exact,
    save_prompt_history,
)


def _history_file(tmp_path: Path) -> Path:
    return tmp_path / "prompt_history.json"


def _shard_file(history_file: Path, key: str) -> Path:
    return history_file.with_suffix("") / f"{key}.json"


def _saved_rows(history_file: Path, key: str) -> list[dict]:
    return json.loads(_shard_file(history_file, key).read_text(encoding="utf-8"))[
        "prompts"
    ]


def _load(history_file: Path) -> list[PromptEntry]:
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        return load_prompt_history()


def _record(
    text: str,
    origin: PromptOrigin | None,
    monkeypatch: pytest.MonkeyPatch,
    history_file: Path,
) -> None:
    monkeypatch.delenv("SASE_AGENT", raising=False)
    with (
        patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file),
        patch(
            "sase.history.prompt_store.generate_timestamp",
            return_value="251231_143052",
        ),
    ):
        add_or_update_prompt(text, origin=origin)


def test_origin_round_trip_through_shard_io(tmp_path: Path, monkeypatch) -> None:
    """Typed and generated origins persist; invalid values are ignored."""
    history_file = _history_file(tmp_path)
    _record("typed prompt written here now", "typed", monkeypatch, history_file)
    _record("generated prompt written here now", "generated", monkeypatch, history_file)

    rows = _saved_rows(history_file, "2512")
    by_text = {row["text"]: row for row in rows}
    assert by_text["typed prompt written here now"]["origin"] == "typed"
    assert by_text["generated prompt written here now"]["origin"] == "generated"

    assert (
        prompt_entry_from_json(
            {"text": "x", "timestamp": "t", "last_used": "u", "origin": "bogus"}
        ).origin
        is None
    )
    assert (
        prompt_entry_from_json({"text": "x", "timestamp": "t", "last_used": "u"}).origin
        is None
    )


def test_origin_omitted_when_unset(tmp_path: Path, monkeypatch) -> None:
    """Rows without an origin keep the legacy on-disk shape."""
    history_file = _history_file(tmp_path)
    _record("plain prompt written here now", None, monkeypatch, history_file)

    (row,) = _saved_rows(history_file, "2512")
    assert "origin" not in row
    assert _load(history_file)[0].origin is None


def test_origin_merge_never_downgrades(tmp_path: Path, monkeypatch) -> None:
    """Typed beats generated beats None on repeat recordings."""
    history_file = _history_file(tmp_path)
    monkeypatch.delenv("SASE_AGENT", raising=False)
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        with patch(
            "sase.history.prompt_store.generate_timestamp",
            return_value="251231_100000",
        ):
            add_or_update_prompt("merge probe prompt here now", origin="generated")
        with patch(
            "sase.history.prompt_store.generate_timestamp",
            return_value="251231_110000",
        ):
            add_or_update_prompt("merge probe prompt here now", origin=None)
        assert load_prompt_history()[0].origin == "generated"

        with patch(
            "sase.history.prompt_store.generate_timestamp",
            return_value="251231_120000",
        ):
            add_or_update_prompt("merge probe prompt here now", origin="typed")
        assert load_prompt_history()[0].origin == "typed"

        with patch(
            "sase.history.prompt_store.generate_timestamp",
            return_value="251231_130000",
        ):
            add_or_update_prompt("merge probe prompt here now", origin="generated")
        assert load_prompt_history()[0].origin == "typed"


def test_failed_launch_records_origin(tmp_path: Path, monkeypatch) -> None:
    """Failed-launch recovery writes carry the caller origin."""
    history_file = _history_file(tmp_path)
    monkeypatch.delenv("SASE_AGENT", raising=False)
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        record_failed_launch_prompt("failed typed prompt", origin="typed")
        record_failed_launch_prompt("failed generated prompt", origin="generated")

    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        by_text = {entry.text: entry for entry in load_prompt_history()}
    assert by_text["failed typed prompt"].origin == "typed"
    assert by_text["failed generated prompt"].origin == "generated"


def test_agent_context_forces_generated(tmp_path: Path, monkeypatch) -> None:
    """Inside a SASE agent, typed origins are recorded as generated."""
    history_file = _history_file(tmp_path)
    monkeypatch.setenv("SASE_AGENT", "1")
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        add_or_update_prompt("agent typed prompt recorded here", origin="typed")
        add_or_update_prompt("agent unknown prompt recorded here")

    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        by_text = {entry.text: entry for entry in load_prompt_history()}
    assert by_text["agent typed prompt recorded here"].origin == "generated"
    assert by_text["agent unknown prompt recorded here"].origin is None


def test_dedup_prefers_typed_origin() -> None:
    """Dedup keeps newest timestamps but the strongest origin."""
    entries = dedup_prompt_entries_newest_first(
        iter(
            [
                PromptEntry(
                    text="same prompt text here",
                    timestamp="251231_120000",
                    last_used="251231_120000",
                    origin="generated",
                ),
                PromptEntry(
                    text="same prompt text here",
                    timestamp="251231_100000",
                    last_used="251231_100000",
                    origin="typed",
                ),
            ]
        )
    )
    assert len(entries) == 1
    assert entries[0].origin == "typed"
    assert entries[0].timestamp == "251231_100000"


def test_rewrite_preserves_origin(tmp_path: Path) -> None:
    """Exact-text rewrites keep the row origin."""
    history_file = _history_file(tmp_path)
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        save_prompt_history(
            [
                PromptEntry(
                    text="old prompt text here now",
                    timestamp="260601_000000",
                    last_used="260601_000000",
                    origin="typed",
                )
            ]
        )
        changed = rewrite_prompt_text_exact(
            "old prompt text here now", "new prompt text here now"
        )

    assert changed == 1
    (entry,) = _load(history_file)
    assert entry.text == "new prompt text here now"
    assert entry.origin == "typed"


def test_segments_inherit_origin(tmp_path: Path, monkeypatch) -> None:
    """Multi-prompt segment rows inherit the recording origin."""
    history_file = _history_file(tmp_path)
    monkeypatch.delenv("SASE_AGENT", raising=False)
    text = (
        "first segment text is long enough here\n---\n"
        "second segment text is long enough here"
    )
    with (
        patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file),
        patch(
            "sase.history.prompt_store.generate_timestamp",
            return_value="251231_143052",
        ),
    ):
        add_or_update_prompt(text, origin="generated")

    origins = {entry.origin for entry in _load(history_file)}
    assert origins == {"generated"}


def test_single_agent_launch_threads_origin(monkeypatch) -> None:
    """The single-agent launch path forwards origin to history."""
    from sase.agent import launch_cwd_single

    monkeypatch.delenv("SASE_AGENT", raising=False)
    monkeypatch.setattr("sase.workspace_provider.get_workflow_names", lambda: set())
    monkeypatch.setattr(
        "sase.agent.launch_validation.validate_launch_name_requests",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        launch_cwd_single,
        "plan_single_agent_name",
        lambda *args, **kwargs: (kwargs.get("extra_env"), None),
    )
    monkeypatch.setattr(
        "sase.agent.launch_executor.execute_launch_plan",
        lambda *args, **kwargs: SimpleNamespace(results=[SimpleNamespace(pid=1)]),
    )
    seen: dict[str, object] = {}

    def _capture(text: str, **kwargs: object) -> None:
        seen["text"] = text
        seen.update(kwargs)

    monkeypatch.setattr("sase.history.prompt.add_or_update_prompt", _capture)

    launch_cwd_single.launch_single_agent(
        "please do something useful right now",
        project_file="home.sase",
        project_name="home",
        is_home_mode=True,
        workspace_num=0,
        extra_env=None,
        timestamp="260929_071614",
        record_failed_launch_prompt=lambda text: None,
        origin="typed",
    )
    assert seen["origin"] == "typed"
