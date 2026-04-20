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
            with patch("sase.agent.repeat_launcher.wait_for_agent_completion"):
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
            with patch("sase.agent.repeat_launcher.wait_for_agent_completion"):
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
                with patch("sase.agent.repeat_launcher.wait_for_agent_completion"):
                    specs = spawn_repeat_batch(
                        "%r:2 do X",
                        base_spawn_fn=lambda _s: None,
                        sleep_between=0.0,
                    )
        assert [s.name for s in specs] == ["c.1", "c.2"]

    def test_waits_between_spawns_sequentially(self, tmp_path: Path) -> None:
        """spawn_k+1 must only run after wait_k — no fan-out."""
        events: list[tuple[str, str]] = []

        def fake_spawn(spec: RepeatAgentSpec) -> None:
            events.append(("spawn", spec.name))

        def fake_wait(name: str) -> None:
            events.append(("wait", name))

        with patch.object(Path, "home", return_value=tmp_path):
            with patch(
                "sase.agent.repeat_launcher.wait_for_agent_completion",
                side_effect=fake_wait,
            ):
                spawn_repeat_batch(
                    "%r:3 %n:qq do X",
                    base_spawn_fn=fake_spawn,
                    sleep_between=0.0,
                )

        assert events == [
            ("spawn", "qq.1"),
            ("wait", "qq.1"),
            ("spawn", "qq.2"),
            ("wait", "qq.2"),
            ("spawn", "qq.3"),
        ]

    def test_no_wait_after_last_spawn(self, tmp_path: Path) -> None:
        """Don't wait after the last agent — nothing to gate on."""
        wait_calls: list[str] = []

        with patch.object(Path, "home", return_value=tmp_path):
            with patch(
                "sase.agent.repeat_launcher.wait_for_agent_completion",
                side_effect=wait_calls.append,
            ):
                spawn_repeat_batch(
                    "%r:3 %n:pp do X",
                    base_spawn_fn=lambda _s: None,
                    sleep_between=0.0,
                )

        assert wait_calls == ["pp.1", "pp.2"]  # N-1 waits

    def test_sleep_cushion_after_each_wait(self, tmp_path: Path) -> None:
        """Keep a small cushion between completion and next spawn."""
        sleep_calls: list[float] = []
        with patch.object(Path, "home", return_value=tmp_path):
            with patch("sase.agent.repeat_launcher.wait_for_agent_completion"):
                with patch(
                    "sase.agent.repeat_launcher.time.sleep",
                    side_effect=sleep_calls.append,
                ):
                    spawn_repeat_batch(
                        "%r:4 %n:qq do X",
                        base_spawn_fn=lambda _s: None,
                        sleep_between=0.25,
                    )
        assert sleep_calls == [0.25, 0.25, 0.25]  # N-1 cushions

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
