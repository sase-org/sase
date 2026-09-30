"""Tests for the prompt-history origin (typed vs generated) marker."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from sase.agent.launch_types import AgentLaunchResult
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


def _patch_history_sinks(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[str], list[str]]:
    """Capture placeholder and Stash writes instead of touching the stores."""
    placeholders: list[str] = []
    stashes: list[str] = []
    monkeypatch.setattr(
        "sase.history.prompt_placeholders.record_prompt_placeholders",
        lambda text: placeholders.append(text),
    )
    monkeypatch.setattr(
        "sase.agent.failed_launch_prompt_stash.stash_failed_launch_prompt",
        lambda text, **kwargs: stashes.append(text),
    )
    return placeholders, stashes


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


def _launch_result(pid: int = 1234) -> AgentLaunchResult:
    return AgentLaunchResult(
        pid=pid,
        workspace_num=7,
        workspace_dir="/workspace/7",
        output_path="/tmp/out.txt",
        project_file="/tmp/projects/proj/proj.sase",
        project_name="proj",
        workflow_name="ace(run)-260101_120000",
        cl_name="proj",
        timestamp="260101_120000",
    )


def _isolated_successful_cwd_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock the spawn machinery so ``launch_agents_from_cwd`` succeeds."""
    from tests._workspace_provider_helpers import patch_no_workspace_metadata

    patch_no_workspace_metadata(monkeypatch)
    monkeypatch.setattr(
        "sase.main.utils.ensure_project_file_and_get_workspace_num",
        lambda create_missing=False: (None, None, None),
    )
    monkeypatch.setattr(
        "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
        lambda count, **kwargs: [f"ts-{index}" for index in range(count)],
    )
    monkeypatch.setattr("sase.agent.names.get_reserved_agent_names", lambda: set())
    execution = SimpleNamespace(results=[_launch_result()])
    monkeypatch.setattr(
        "sase.agent.launch_executor.execute_launch_plan",
        lambda *args, **kwargs: execution,
    )


def test_origin_round_trip_through_shard_io(tmp_path: Path, monkeypatch) -> None:
    """Typed and generated origins persist; invalid values are ignored."""
    history_file = _history_file(tmp_path)
    _record("typed prompt written here now", "typed", monkeypatch, history_file)
    monkeypatch.delenv("SASE_AGENT", raising=False)
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        # Legacy generated rows still persist through the storage layer; only
        # the writers refuse to create new ones.
        save_prompt_history(
            [
                PromptEntry(
                    text="typed prompt written here now",
                    timestamp="251231_143052",
                    last_used="251231_143052",
                    origin="typed",
                ),
                PromptEntry(
                    text="generated prompt written here now",
                    timestamp="251231_143052",
                    last_used="251231_143052",
                    origin="generated",
                ),
            ]
        )

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
        # A legacy generated row upgrades to typed and never downgrades back:
        # generated writes are no-ops, so they cannot touch the row at all.
        save_prompt_history(
            [
                PromptEntry(
                    text="merge probe prompt here now",
                    timestamp="251231_100000",
                    last_used="251231_100000",
                    origin="generated",
                )
            ]
        )
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
        (entry,) = load_prompt_history()
        assert entry.origin == "typed"
        assert entry.last_used == "251231_120000"


def test_failed_launch_records_origin(tmp_path: Path, monkeypatch) -> None:
    """A typed failure records; a generated failure writes no row or Stash."""
    history_file = _history_file(tmp_path)
    monkeypatch.delenv("SASE_AGENT", raising=False)
    _, stashes = _patch_history_sinks(monkeypatch)
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        record_failed_launch_prompt("failed typed prompt", origin="typed")
        record_failed_launch_prompt("failed generated prompt", origin="generated")

    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        by_text = {entry.text: entry for entry in load_prompt_history()}
    assert by_text["failed typed prompt"].origin == "typed"
    assert "failed generated prompt" not in by_text
    assert stashes == ["failed typed prompt"]


def test_agent_context_writes_nothing(tmp_path: Path, monkeypatch) -> None:
    """Inside a SASE agent, no origin writes anything."""
    history_file = _history_file(tmp_path)
    monkeypatch.setenv("SASE_AGENT", "1")
    placeholders, stashes = _patch_history_sinks(monkeypatch)
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        add_or_update_prompt("agent typed prompt recorded here", origin="typed")
        add_or_update_prompt("agent unknown prompt recorded here")
        record_failed_launch_prompt("agent failed prompt recorded here", origin="typed")

    assert _load(history_file) == []
    assert placeholders == []
    assert stashes == []


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
        add_or_update_prompt(text, origin="typed")

    origins = {entry.origin for entry in _load(history_file)}
    assert origins == {"typed"}


def test_single_agent_launch_threads_origin(monkeypatch) -> None:
    """The single-agent launch path records the recorder's text and origin."""
    from sase.agent import launch_cwd_single
    from sase.agent.launch_cwd_common import LaunchHistoryRecorder

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
        "expanded single member text here",
        project_file="home.sase",
        project_name="home",
        is_home_mode=True,
        workspace_num=0,
        extra_env=None,
        timestamp="260929_071614",
        recorder=LaunchHistoryRecorder(
            text="please do something useful right now", origin="typed"
        ),
    )
    assert seen["text"] == "please do something useful right now"
    assert seen["origin"] == "typed"


def test_generated_add_writes_nothing(tmp_path: Path, monkeypatch) -> None:
    """A generated add leaves the shard, placeholders, and Stash untouched."""
    history_file = _history_file(tmp_path)
    monkeypatch.delenv("SASE_AGENT", raising=False)
    placeholders, stashes = _patch_history_sinks(monkeypatch)
    with (
        patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file),
        patch(
            "sase.history.prompt_store.generate_timestamp",
            return_value="251231_143052",
        ),
    ):
        add_or_update_prompt(
            "generated prompt with a <placeholder> written here",
            origin="generated",
        )

    assert _load(history_file) == []
    assert not history_file.with_suffix("").exists()
    assert placeholders == []
    assert stashes == []


def test_generated_failure_writes_nothing(tmp_path: Path, monkeypatch) -> None:
    """A generated failure leaves the shard, placeholders, and Stash untouched."""
    history_file = _history_file(tmp_path)
    monkeypatch.delenv("SASE_AGENT", raising=False)
    placeholders, stashes = _patch_history_sinks(monkeypatch)
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        record_failed_launch_prompt(
            "generated failure with a <placeholder> here", origin="generated"
        )

    assert _load(history_file) == []
    assert not history_file.with_suffix("").exists()
    assert placeholders == []
    assert stashes == []


def test_generated_add_does_not_bump_typed_row(tmp_path: Path, monkeypatch) -> None:
    """A generated reuse of typed text leaves that row's last_used alone."""
    history_file = _history_file(tmp_path)
    monkeypatch.delenv("SASE_AGENT", raising=False)
    _patch_history_sinks(monkeypatch)
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        with patch(
            "sase.history.prompt_store.generate_timestamp",
            return_value="251231_100000",
        ):
            add_or_update_prompt("already typed prompt here now", origin="typed")
        with patch(
            "sase.history.prompt_store.generate_timestamp",
            return_value="251231_120000",
        ):
            add_or_update_prompt("already typed prompt here now", origin="generated")

    (entry,) = _load(history_file)
    assert entry.origin == "typed"
    assert entry.last_used == "251231_100000"


def _bead_work_launch(
    monkeypatch: pytest.MonkeyPatch, origin: PromptOrigin | None
) -> list[Any]:
    """Run the planned bead-work adapter with spawn machinery mocked."""
    from sase.agent import launch_cwd
    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        AgentOwnerIdentity,
    )
    from tests.agent._launch_guard_helpers import install_disables

    identity = AgentIdentitySnapshot(
        AgentOwnerIdentity("alice", "athena"),
        ("athena",),
    )
    monkeypatch.setattr(
        AgentIdentitySnapshot,
        "current",
        classmethod(lambda _cls: identity),
    )
    segments = [
        "#git:proj\n%id(proj-epic.1, bead=proj-epic.1)\n"
        "%clan(proj-epic, tribe=epic)\n%model:@worker\n"
        "%auto\n#bd/work_phase_bead:proj-epic.1",
        "#git:proj\n%id(land, clan=proj-epic, bead=proj-epic)\n"
        "%auto\n%w:proj-epic.1\n#bd/land_epic:proj-epic",
    ]
    envs = [
        {"SASE_BEAD_ID": "proj-epic.1", "SASE_INTERNAL_AGENT_NAME_BYPASS": "1"},
        {"SASE_BEAD_ID": "proj-epic", "SASE_INTERNAL_AGENT_NAME_BYPASS": "1"},
    ]

    def fake_launch_multi(**kwargs: Any) -> list[object]:
        return [object(), object()]

    monkeypatch.setattr(
        "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
        fake_launch_multi,
    )
    monkeypatch.setattr("sase.agent.names.get_reserved_agent_names", lambda: set())
    monkeypatch.setattr(
        "sase.agent.names.mutate_registered_name_reservations",
        lambda _reservations: None,
    )
    install_disables(monkeypatch, {})

    return launch_cwd.launch_planned_bead_work_agents(
        segments=segments,
        segment_extra_env=envs,
        expected_names={"proj-epic.1", "proj-epic.land"},
        project_name="proj",
        origin=origin,
    )


def test_bead_work_launch_records_no_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bead-work launch with N segments records 0 history rows."""
    history_file = _history_file(tmp_path)
    monkeypatch.delenv("SASE_AGENT", raising=False)
    placeholders, stashes = _patch_history_sinks(monkeypatch)
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        results = _bead_work_launch(monkeypatch, "generated")

    assert len(results) == 2
    assert _load(history_file) == []
    assert placeholders == []
    assert stashes == []


def test_chop_env_launch_records_nothing_on_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Chop markers in extra_env suppress the success write."""
    from sase.agent.launcher import launch_agents_from_cwd
    from sase.axe.chop_agents import ENV_CHOP_NAME

    monkeypatch.delenv("SASE_AGENT", raising=False)
    history_file = _history_file(tmp_path)
    placeholders, stashes = _patch_history_sinks(monkeypatch)
    _isolated_successful_cwd_launch(monkeypatch)

    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        launch_agents_from_cwd(
            "please refresh the project documentation now",
            extra_env={ENV_CHOP_NAME: "refresh_docs"},
            origin=None,
        )

    assert _load(history_file) == []
    assert placeholders == []
    assert stashes == []


def test_chop_env_launch_records_nothing_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Chop markers in extra_env suppress the failure write and Stash."""
    from sase.agent.launcher import launch_agents_from_cwd
    from sase.axe.chop_agents import ENV_CHOP_NAME

    monkeypatch.delenv("SASE_AGENT", raising=False)
    history_file = _history_file(tmp_path)
    placeholders, stashes = _patch_history_sinks(monkeypatch)
    _isolated_successful_cwd_launch(monkeypatch)

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("name taken")

    monkeypatch.setattr(
        "sase.agent.launch_validation.validate_launch_name_requests",
        _boom,
    )

    with (
        patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file),
        pytest.raises(RuntimeError, match="name taken"),
    ):
        launch_agents_from_cwd(
            "please refresh the project documentation now",
            extra_env={ENV_CHOP_NAME: "refresh_docs"},
            origin=None,
        )

    assert _load(history_file) == []
    assert placeholders == []
    assert stashes == []


def test_job_process_env_does_not_suppress_typed_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SASE_JOB_NAME in the process env still records (Telegram runs in jobs)."""
    monkeypatch.setenv("SASE_JOB_NAME", "nightly_tick")
    monkeypatch.delenv("SASE_AGENT", raising=False)
    history_file = _history_file(tmp_path)
    _patch_history_sinks(monkeypatch)
    _isolated_successful_cwd_launch(monkeypatch)

    from sase.agent.launcher import launch_agents_from_cwd

    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        launch_agents_from_cwd("please summarize these project notes now", origin=None)

    (entry,) = _load(history_file)
    assert entry.origin is None


def test_effective_prompt_origin_matrix(monkeypatch: pytest.MonkeyPatch) -> None:
    """The resolver honors explicit, launch-env, and process provenance."""
    from sase.axe.chop_agents import ENV_CHOP_NAME
    from sase.history.prompt_store_mutations import effective_prompt_origin

    monkeypatch.delenv("SASE_AGENT", raising=False)
    assert effective_prompt_origin("generated") == "generated"
    assert effective_prompt_origin("typed") == "typed"
    assert effective_prompt_origin(None) is None
    assert (
        effective_prompt_origin("typed", launch_envs=({ENV_CHOP_NAME: "job"},))
        == "generated"
    )
    assert (
        effective_prompt_origin(None, launch_envs=({ENV_CHOP_NAME: "job"},))
        == "generated"
    )
    assert effective_prompt_origin("typed", launch_envs=(None, {})) == "typed"

    monkeypatch.setenv("SASE_AGENT", "worker.1")
    assert effective_prompt_origin("typed") == "generated"
    assert effective_prompt_origin(None) == "generated"
