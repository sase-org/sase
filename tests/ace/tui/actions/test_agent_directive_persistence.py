"""Tests for worker-safe agent directive persistence helpers."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.actions.agents._directive_persistence import (
    AgentDirectivePersistenceSpec,
    AgentMetaPatch,
    AgentTagStorePatch,
    persist_agent_directive_update,
    waiting_marker_patch_for_token,
)
from sase.ace.tui.models.agent import AgentType
from sase.history.prompt_store import (
    PromptEntry,
    load_prompt_history,
    save_prompt_history,
)
from sase.xprompt.directive_edit import (
    PromptWaitDirective,
    set_prompt_name,
    set_prompt_wait,
)


def _entry(text: str, timestamp: str) -> PromptEntry:
    return PromptEntry(text=text, timestamp=timestamp, last_used=timestamp)


def test_persist_agent_directive_update_rewrites_prompt_artifacts_and_history(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    old_prompt = "%id:old\nDo work"
    new_prompt = "%id:new\nDo work"
    (artifacts / "raw_xprompt.md").write_text(old_prompt, encoding="utf-8")
    (artifacts / "submitted_xprompt.md").write_text(old_prompt, encoding="utf-8")
    history_file = tmp_path / "prompt_history.json"

    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        save_prompt_history([_entry(old_prompt, "260601_000000")])
        result = persist_agent_directive_update(
            AgentDirectivePersistenceSpec(
                artifacts_dir=artifacts,
                prompt_mutator=lambda prompt: set_prompt_name(prompt, "new"),
                meta_patch=AgentMetaPatch(set_values={"name": "new"}),
            )
        )

        assert result.raw_prompt_updated is True
        assert result.submitted_prompt_updated is True
        assert result.history_rewrites == 1
        assert (artifacts / "raw_xprompt.md").read_text(encoding="utf-8") == new_prompt
        assert (artifacts / "submitted_xprompt.md").read_text(
            encoding="utf-8"
        ) == new_prompt
        assert [entry.text for entry in load_prompt_history()] == [new_prompt]
        assert json.loads((artifacts / "agent_meta.json").read_text())["name"] == "new"


def test_persist_agent_directive_update_leaves_diverged_submitted_prompt(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "raw_xprompt.md").write_text("%id:old\nDo work", encoding="utf-8")
    (artifacts / "submitted_xprompt.md").write_text("historical", encoding="utf-8")

    result = persist_agent_directive_update(
        AgentDirectivePersistenceSpec(
            artifacts_dir=artifacts,
            prompt_mutator=lambda prompt: set_prompt_name(prompt, "new"),
        )
    )

    assert result.submitted_prompt_updated is False
    assert (artifacts / "submitted_xprompt.md").read_text(encoding="utf-8") == (
        "historical"
    )


def test_persist_agent_directive_update_finishes_when_history_is_corrupt(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    old_prompt = "%id:old\nDo work"
    new_prompt = "%id:new\nDo work"
    (artifacts / "raw_xprompt.md").write_text(old_prompt, encoding="utf-8")
    history_file = tmp_path / "prompt_history.json"
    history_dir = tmp_path / "prompt_history"
    history_dir.mkdir()
    (history_dir / "2606.json").write_text("{", encoding="utf-8")

    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        result = persist_agent_directive_update(
            AgentDirectivePersistenceSpec(
                artifacts_dir=artifacts,
                prompt_mutator=lambda prompt: set_prompt_name(prompt, "new"),
                meta_patch=AgentMetaPatch(set_values={"name": "new"}),
            )
        )

    assert result.raw_prompt_updated is True
    assert result.history_rewrites == 0
    assert result.meta_updated is True
    assert (artifacts / "raw_xprompt.md").read_text(encoding="utf-8") == new_prompt
    assert json.loads((artifacts / "agent_meta.json").read_text())["name"] == "new"


def test_agent_meta_edit_migrates_legacy_tag_to_tribe(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"tag": "legacy", "name": "old"}),
        encoding="utf-8",
    )

    result = persist_agent_directive_update(
        AgentDirectivePersistenceSpec(
            artifacts_dir=artifacts,
            meta_patch=AgentMetaPatch(set_values={"name": "new"}),
        )
    )

    assert result.meta_updated is True
    assert json.loads((artifacts / "agent_meta.json").read_text()) == {
        "tribe": "legacy",
        "name": "new",
    }


def test_persist_agent_directive_update_writes_waiting_marker_and_meta(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "raw_xprompt.md").write_text("%w:old\nDo work", encoding="utf-8")
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"wait_for": ["old"], "wait_duration": 300.0}),
        encoding="utf-8",
    )

    result = persist_agent_directive_update(
        AgentDirectivePersistenceSpec(
            artifacts_dir=artifacts,
            prompt_mutator=lambda prompt: set_prompt_wait(
                prompt,
                PromptWaitDirective(agents=("dep",), time_token=None),
            ),
            meta_patch=AgentMetaPatch(
                set_values={"wait_for": ["dep"]},
                remove_keys=("wait_for", "wait_duration", "wait_until"),
            ),
            waiting_marker=waiting_marker_patch_for_token(wait_names=("dep",)),
        )
    )

    assert result.raw_prompt_updated is True
    assert result.meta_updated is True
    assert result.waiting_updated is True
    assert (artifacts / "raw_xprompt.md").read_text(encoding="utf-8") == (
        "%wait(dep)\nDo work"
    )
    assert json.loads((artifacts / "agent_meta.json").read_text()) == {
        "wait_for": ["dep"]
    }
    assert json.loads((artifacts / "waiting.json").read_text())["waiting_for"] == [
        "dep"
    ]


def test_persist_agent_directive_update_sets_and_unsets_tribe_store(
    tmp_path: Path,
) -> None:
    tribes_file = tmp_path / "agent_tribes.json"
    identity = (AgentType.WORKFLOW, "cl", "260601000000")
    with patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribes_file):
        set_result = persist_agent_directive_update(
            AgentDirectivePersistenceSpec(
                artifacts_dir=tmp_path / "artifacts",
                tag_patch=AgentTagStorePatch(identity=identity, tag="review"),
            )
        )
        unset_result = persist_agent_directive_update(
            AgentDirectivePersistenceSpec(
                artifacts_dir=tmp_path / "artifacts",
                tag_patch=AgentTagStorePatch(identity=identity, tag=None),
            )
        )

    assert set_result.tag_updated is True
    assert unset_result.tag_updated is True
    assert json.loads(tribes_file.read_text()) == []
