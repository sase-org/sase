"""Tests for sase.agent.repeat_launcher."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.names import NameCollisionError
from sase.agent.repeat_launcher import (
    RepeatAgentSpec,
    extract_repeat_and_name,
    spawn_repeat_batch,
)


class TestExtractRepeatAndName:
    def test_parses_repeat_and_name(self) -> None:
        count, base, cleaned = extract_repeat_and_name("%r:4 %n:sase-z do X")
        assert count == 4
        assert base == "sase-z"
        assert "%r" not in cleaned
        assert "%n" not in cleaned
        assert "do X" in cleaned

    def test_parses_canonical_names(self) -> None:
        count, base, cleaned = extract_repeat_and_name("%repeat:2 %name:foo body")
        assert count == 2
        assert base == "foo"
        assert "body" in cleaned
        assert "%repeat" not in cleaned
        assert "%name" not in cleaned

    def test_returns_none_when_no_repeat(self) -> None:
        count, base, cleaned = extract_repeat_and_name("do X")
        assert count is None
        assert base is None
        assert cleaned == "do X"

    def test_returns_none_when_no_percent(self) -> None:
        count, base, cleaned = extract_repeat_and_name("plain prompt")
        assert count is None
        assert base is None
        assert cleaned == "plain prompt"

    def test_single_iteration_is_noop(self) -> None:
        count, base, cleaned = extract_repeat_and_name("%r:1 do X")
        assert count is None
        assert base is None
        # Original prompt returned unchanged (single-iteration is no-op)
        assert cleaned == "%r:1 do X"

    def test_strips_bare_name(self) -> None:
        count, base, cleaned = extract_repeat_and_name("%r:3 %n do X")
        assert count == 3
        assert base is None  # bare %n means auto-gen
        assert "do X" in cleaned

    def test_preserves_other_directives(self) -> None:
        _, _, cleaned = extract_repeat_and_name("%r:3 %model:opus %wait do X")
        assert "%model:opus" in cleaned
        assert "%wait" in cleaned
        assert "%r" not in cleaned

    def test_ignores_repeat_in_fenced_block(self) -> None:
        prompt = "do X\n```\n%r:5\n```\n"
        count, _, cleaned = extract_repeat_and_name(prompt)
        assert count is None
        assert "%r:5" in cleaned  # preserved inside the fence


class TestSpawnRepeatBatch:
    def test_returns_empty_when_no_repeat(self) -> None:
        calls: list[RepeatAgentSpec] = []
        specs = spawn_repeat_batch(
            "no repeat here",
            base_spawn_fn=calls.append,
        )
        assert specs == []
        assert calls == []

    def test_returns_empty_for_single_iteration(self) -> None:
        calls: list[RepeatAgentSpec] = []
        specs = spawn_repeat_batch(
            "%r:1 do X",
            base_spawn_fn=calls.append,
        )
        assert specs == []
        assert calls == []

    def test_calls_spawn_fn_n_times(self, tmp_path: Path) -> None:
        calls: list[RepeatAgentSpec] = []
        with patch.object(Path, "home", return_value=tmp_path):
            specs = spawn_repeat_batch(
                "%r:3 %n:zz do X",
                base_spawn_fn=calls.append,
                sleep_between=0.0,
            )
        assert len(specs) == 3
        assert [s.name for s in specs] == ["zz.1", "zz.2", "zz.3"]
        assert [s.iteration for s in specs] == [1, 2, 3]
        assert [s.total for s in specs] == [3, 3, 3]
        assert calls == specs

    def test_specs_have_n_injected(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            specs = spawn_repeat_batch(
                "%r:2 %n:aa do Y",
                base_spawn_fn=lambda _s: None,
                sleep_between=0.0,
            )
        assert specs[0].prompt.startswith("%n:aa.1")
        assert specs[1].prompt.startswith("%n:aa.2")
        assert "do Y" in specs[0].prompt
        assert "do Y" in specs[1].prompt

    def test_auto_name_delegates_to_get_next_auto_name(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            with patch(
                "sase.agent.repeat_launcher.reserve_repeat_name_base",
                return_value="c",
            ):
                specs = spawn_repeat_batch(
                    "%r:2 do X",
                    base_spawn_fn=lambda _s: None,
                    sleep_between=0.0,
                )
        assert [s.name for s in specs] == ["c.1", "c.2"]

    def test_stagger_sleep(self, tmp_path: Path) -> None:
        sleep_calls: list[float] = []
        with patch.object(Path, "home", return_value=tmp_path):
            with patch(
                "sase.agent.repeat_launcher.time.sleep",
                side_effect=lambda s: sleep_calls.append(s),
            ):
                spawn_repeat_batch(
                    "%r:4 %n:qq do X",
                    base_spawn_fn=lambda _s: None,
                    sleep_between=0.25,
                )
        assert sleep_calls == [0.25, 0.25, 0.25]  # N-1 sleeps

    def test_first_iteration_has_no_wait(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            specs = spawn_repeat_batch(
                "%r:3 %n:ww do X",
                base_spawn_fn=lambda _s: None,
                sleep_between=0.0,
            )
        assert specs[0].prompt.startswith("%n:ww.1\n")
        assert "%wait:ww" not in specs[0].prompt

    def test_later_iterations_wait_on_predecessor(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            specs = spawn_repeat_batch(
                "%r:4 %n:ww do X",
                base_spawn_fn=lambda _s: None,
                sleep_between=0.0,
            )
        assert specs[1].prompt.startswith("%n:ww.2\n%wait:ww.1\n")
        assert specs[2].prompt.startswith("%n:ww.3\n%wait:ww.2\n")
        assert specs[3].prompt.startswith("%n:ww.4\n%wait:ww.3\n")

    def test_preexisting_user_wait_is_preserved(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            specs = spawn_repeat_batch(
                "%r:2 %n:ww %wait:other do X",
                base_spawn_fn=lambda _s: None,
                sleep_between=0.0,
            )
        # The user's %wait:other survives prompt cleanup and coexists with
        # the injected %wait:ww.1 for iteration 2.
        assert "%wait:other" in specs[0].prompt
        assert "%wait:other" in specs[1].prompt
        assert "%wait:ww.1" in specs[1].prompt

    def test_explicit_base_collision_raises(self, tmp_path: Path) -> None:
        project_dir = (
            tmp_path / ".sase" / "projects" / "proj" / "artifacts" / "ace-run" / "run1"
        )
        project_dir.mkdir(parents=True)
        import os

        meta = {"name": "sase-z.2", "pid": os.getpid()}
        (project_dir / "agent_meta.json").write_text(json.dumps(meta))

        with patch.object(Path, "home", return_value=tmp_path):
            with pytest.raises(NameCollisionError):
                spawn_repeat_batch(
                    "%r:4 %n:sase-z do X",
                    base_spawn_fn=lambda _s: None,
                    sleep_between=0.0,
                )
