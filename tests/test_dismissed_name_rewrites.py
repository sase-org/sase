"""Tests for Phase 3 wait/resume reference rewrites.

Covers the prompt-text and structured-data helpers in
``sase.agent.dismissed_name_rewrites`` plus the wiring that hands a name
map from the cleanup intent planner to dependent agents and the
asynchronous persistence transactions.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.dismissed_name_rewrites import (
    _rewrite_artifact_json_files,
    _rewrite_artifact_prompt,
    _rewrite_directive_text,
    _rewrite_resume_directives,
    _rewrite_wait_directives,
    rewrite_dismissed_references,
)


# ---------------------------------------------------------------------------
# Wait-directive rewrites
# ---------------------------------------------------------------------------


class TestRewriteWaitDirectives:
    def test_colon_form_single_name(self) -> None:
        assert (
            _rewrite_wait_directives("%w:foo do thing", {"foo": "260428.foo"})
            == "%w:260428.foo do thing"
        )

    def test_long_alias_colon(self) -> None:
        assert (
            _rewrite_wait_directives("%wait:foo", {"foo": "260428.foo"})
            == "%wait:260428.foo"
        )

    def test_comma_list_partial_rewrite(self) -> None:
        # Only the matched name is rewritten; the rest stay verbatim.
        assert (
            _rewrite_wait_directives("%w:foo,bar", {"foo": "260428.foo"})
            == "%w:260428.foo,bar"
        )

    def test_paren_form(self) -> None:
        assert (
            _rewrite_wait_directives("%w(foo, bar)", {"bar": "260428.bar"})
            == "%w(foo, 260428.bar)"
        )

    def test_backtick_arg(self) -> None:
        assert (
            _rewrite_wait_directives("%w:`foo`", {"foo": "260428.foo"})
            == "%w:`260428.foo`"
        )

    def test_skips_substring_collisions(self) -> None:
        # ``foobar`` is not in the map and must not be rewritten just because
        # ``foo`` is — the directive splits on commas, exact match only.
        assert (
            _rewrite_wait_directives("%w:foobar", {"foo": "260428.foo"}) == "%w:foobar"
        )

    def test_unrelated_text_unchanged(self) -> None:
        text = "Wait for foo to finish before resuming."
        assert _rewrite_wait_directives(text, {"foo": "260428.foo"}) == text

    def test_skips_fenced_code_block(self) -> None:
        text = "```\n%w:foo\n```\nthen %w:foo runs"
        rewritten = _rewrite_wait_directives(text, {"foo": "260428.foo"})
        # The fenced example stays as-is; the live directive is rewritten.
        assert "```\n%w:foo\n```" in rewritten
        assert "then %w:260428.foo runs" in rewritten

    def test_skips_disabled_region(self) -> None:
        text = (
            "%xprompts_enabled:false\n%w:foo\n%xprompts_enabled:true\nnow %w:foo here"
        )
        rewritten = _rewrite_wait_directives(text, {"foo": "260428.foo"})
        # Disabled region preserves the marker pair and original directive.
        assert "%xprompts_enabled:false\n%w:foo\n%xprompts_enabled:true" in rewritten
        # Active directive is rewritten.
        assert rewritten.endswith("now %w:260428.foo here")

    def test_empty_map_is_noop(self) -> None:
        text = "%w:foo"
        assert _rewrite_wait_directives(text, {}) == text

    def test_idempotent_when_map_already_applied(self) -> None:
        # Rewriting again with the same map is a no-op once the live name is gone.
        once = _rewrite_wait_directives("%w:foo", {"foo": "260428.foo"})
        assert _rewrite_wait_directives(once, {"foo": "260428.foo"}) == once


# ---------------------------------------------------------------------------
# Resume-directive rewrites
# ---------------------------------------------------------------------------


class TestRewriteResumeDirectives:
    def test_colon_form(self) -> None:
        assert (
            _rewrite_resume_directives("#resume:foo go", {"foo": "260428.foo"})
            == "#resume:260428.foo go"
        )

    def test_paren_form(self) -> None:
        assert (
            _rewrite_resume_directives("#resume(foo)", {"foo": "260428.foo"})
            == "#resume(260428.foo)"
        )

    def test_backtick_paren(self) -> None:
        assert (
            _rewrite_resume_directives("#resume(`foo`)", {"foo": "260428.foo"})
            == "#resume(`260428.foo`)"
        )

    def test_backtick_colon(self) -> None:
        assert (
            _rewrite_resume_directives("#resume:`foo`", {"foo": "260428.foo"})
            == "#resume:`260428.foo`"
        )

    def test_resume_by_chat_untouched(self) -> None:
        # ``#resume_by_chat`` argument is a chat path, never an agent name.
        text = "#resume_by_chat:foo.md"
        assert _rewrite_resume_directives(text, {"foo": "260428.foo"}) == text

    def test_unmapped_name_unchanged(self) -> None:
        text = "#resume:bar"
        assert _rewrite_resume_directives(text, {"foo": "260428.foo"}) == text

    def test_skipped_in_fenced_block(self) -> None:
        text = "```\n#resume:foo\n```\n#resume:foo"
        rewritten = _rewrite_resume_directives(text, {"foo": "260428.foo"})
        assert "```\n#resume:foo\n```" in rewritten
        assert rewritten.endswith("#resume:260428.foo")


class TestRewriteDirectiveText:
    def test_combines_wait_and_resume(self) -> None:
        text = "%w:foo then later #resume:foo"
        assert (
            _rewrite_directive_text(text, {"foo": "260428.foo"})
            == "%w:260428.foo then later #resume:260428.foo"
        )


# ---------------------------------------------------------------------------
# Structured-data rewrites
# ---------------------------------------------------------------------------


class TestRewriteArtifactJsonFiles:
    def test_rewrites_agent_meta_wait_for(self, tmp_path: Path) -> None:
        meta = tmp_path / "agent_meta.json"
        meta.write_text(json.dumps({"name": "bar", "wait_for": ["foo", "baz"]}))

        changed = _rewrite_artifact_json_files(tmp_path, {"foo": "260428.foo"})

        assert changed
        data = json.loads(meta.read_text())
        assert data["wait_for"] == ["260428.foo", "baz"]
        # ``name`` must not be touched — it identifies the agent itself,
        # not a dependency reference.
        assert data["name"] == "bar"

    def test_rewrites_waiting_json(self, tmp_path: Path) -> None:
        waiting = tmp_path / "waiting.json"
        waiting.write_text(json.dumps({"waiting_for": ["foo"], "cl_name": "feature_x"}))
        _rewrite_artifact_json_files(tmp_path, {"foo": "260428.foo"})
        assert json.loads(waiting.read_text())["waiting_for"] == ["260428.foo"]

    def test_rewrites_ready_json(self, tmp_path: Path) -> None:
        ready = tmp_path / "ready.json"
        ready.write_text(json.dumps({"resolved_deps": ["foo", "baz"]}))
        _rewrite_artifact_json_files(tmp_path, {"baz": "260428.baz"})
        assert json.loads(ready.read_text())["resolved_deps"] == ["foo", "260428.baz"]

    def test_no_change_returns_false(self, tmp_path: Path) -> None:
        meta = tmp_path / "agent_meta.json"
        meta.write_text(json.dumps({"wait_for": ["bar"]}))
        assert not _rewrite_artifact_json_files(tmp_path, {"foo": "260428.foo"})

    def test_missing_files_silent(self, tmp_path: Path) -> None:
        # Empty dir: no files — call must not raise and reports no change.
        assert not _rewrite_artifact_json_files(tmp_path, {"foo": "260428.foo"})

    def test_corrupt_json_silent(self, tmp_path: Path) -> None:
        (tmp_path / "agent_meta.json").write_text("{not json")
        assert not _rewrite_artifact_json_files(tmp_path, {"foo": "260428.foo"})


class TestRewriteArtifactPrompt:
    def test_rewrites_prompt_directives(self, tmp_path: Path) -> None:
        prompt = tmp_path / "raw_xprompt.md"
        prompt.write_text("Body.\n%w:foo and #resume:foo\n")
        changed = _rewrite_artifact_prompt(tmp_path, {"foo": "260428.foo"})
        assert changed
        assert prompt.read_text() == "Body.\n%w:260428.foo and #resume:260428.foo\n"

    def test_no_change_returns_false(self, tmp_path: Path) -> None:
        prompt = tmp_path / "raw_xprompt.md"
        prompt.write_text("plain prose only")
        assert not _rewrite_artifact_prompt(tmp_path, {"foo": "260428.foo"})

    def test_missing_file_silent(self, tmp_path: Path) -> None:
        assert not _rewrite_artifact_prompt(tmp_path, {"foo": "260428.foo"})


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------


def _make_artifact_dir(tmp_path: Path, ts: str) -> Path:
    artifact_dir = (
        tmp_path / ".sase" / "projects" / "proj" / "artifacts" / "ace-run" / ts
    )
    artifact_dir.mkdir(parents=True)
    return artifact_dir


class TestRewriteDismissedReferences:
    def test_walks_project_artifacts(self, tmp_path: Path) -> None:
        artifact_dir = _make_artifact_dir(tmp_path, "20260428103000")
        (artifact_dir / "agent_meta.json").write_text(json.dumps({"wait_for": ["foo"]}))
        (artifact_dir / "raw_xprompt.md").write_text("%w:foo run it")

        with patch.object(Path, "home", return_value=tmp_path):
            rewrite_dismissed_references({"foo": "260428.foo"})

        assert json.loads((artifact_dir / "agent_meta.json").read_text())[
            "wait_for"
        ] == ["260428.foo"]
        assert (artifact_dir / "raw_xprompt.md").read_text() == "%w:260428.foo run it"

    def test_in_memory_agents_get_waiting_for_rewrite(self, tmp_path: Path) -> None:
        from sase.ace.tui.models.agent import Agent, AgentType

        agent = Agent(
            agent_type=AgentType.RUNNING,
            cl_name="cl_b",
            project_file="/tmp/projects/myproj/myproj.gp",
            status="WAITING",
            start_time=datetime(2026, 4, 28, 9, 0, 0),
            raw_suffix="20260428090000",
            waiting_for=["foo", "bar"],
        )

        with patch.object(Path, "home", return_value=tmp_path):
            rewrite_dismissed_references(
                {"foo": "260428.foo"}, in_memory_agents=[agent]
            )

        assert agent.waiting_for == ["260428.foo", "bar"]

    def test_empty_map_does_nothing(self) -> None:
        # An empty map must short-circuit without scanning the disk.
        with patch.object(Path, "home", side_effect=AssertionError("no scan")):
            rewrite_dismissed_references({})

    def test_unrelated_dependency_untouched(self, tmp_path: Path) -> None:
        artifact_dir = _make_artifact_dir(tmp_path, "20260428103000")
        (artifact_dir / "agent_meta.json").write_text(
            json.dumps({"wait_for": ["foobar"]})
        )

        with patch.object(Path, "home", return_value=tmp_path):
            rewrite_dismissed_references({"foo": "260428.foo"})

        # Phase 3 exit criterion: ``foobar`` is not rewritten by ``foo`` map.
        assert json.loads((artifact_dir / "agent_meta.json").read_text())[
            "wait_for"
        ] == ["foobar"]


# ---------------------------------------------------------------------------
# Dismiss-flow integration
# ---------------------------------------------------------------------------


class TestDismissFlowReferenceRewrites:
    """End-to-end: dismissing renames an agent and updates dependents."""

    def test_dismiss_rewrites_in_memory_waiting_for_of_other_agents(
        self, tmp_path: Path
    ) -> None:
        from tests.test_agent_dismiss_in_memory import (
            FakeDismissApp,
            _make_agent,
            _patch_isolated_home,
        )

        target = _make_agent(
            cl_name="feature_a",
            raw_suffix="20260428100000",
            stop_time=datetime(2026, 4, 28, 12, 0, 0),
            agent_name="foo",
        )
        dependent = _make_agent(
            cl_name="feature_b",
            raw_suffix="20260428110000",
            stop_time=datetime(2026, 4, 28, 13, 0, 0),
            status="WAITING",
            waiting_for=["foo"],
        )

        app = FakeDismissApp()
        app._agents_with_children = [target, dependent]

        patches = _patch_isolated_home(tmp_path)
        for p in patches:
            p.start()
        try:
            app._dismiss_done_agent(target)
        finally:
            for p in patches:
                p.stop()

        assert target.agent_name == "260428.foo"
        # Surviving dependent was rewritten in place.
        assert dependent.waiting_for == ["260428.foo"]

    def test_dismiss_passes_name_map_to_persistence(self, tmp_path: Path) -> None:
        from tests.test_agent_dismiss_in_memory import (
            FakeDismissApp,
            _make_agent,
            _patch_isolated_home,
        )

        target = _make_agent(
            cl_name="feature_a",
            raw_suffix="20260428100000",
            stop_time=datetime(2026, 4, 28, 12, 0, 0),
            agent_name="foo",
        )

        app = FakeDismissApp()
        app._agents_with_children = [target]

        patches = _patch_isolated_home(tmp_path)
        for p in patches:
            p.start()
        try:
            app._dismiss_done_agent(target)
        finally:
            for p in patches:
                p.stop()

        _, args = app._scheduled[0]
        # name_map is the trailing positional arg.
        name_map = args[-1]
        assert name_map == {"foo": "260428.foo"}

    def test_persist_transaction_runs_disk_rewrites(self, tmp_path: Path) -> None:
        from tests.test_agent_dismiss_in_memory import (
            FakeDismissApp,
            _make_agent,
            _patch_isolated_home,
        )

        # Set up a *separate* artifact dir for a dependent agent that
        # waits on ``foo`` so the worker's rewrite has something to do.
        dep_dir = _make_artifact_dir(tmp_path, "20260428110000")
        (dep_dir / "agent_meta.json").write_text(json.dumps({"wait_for": ["foo"]}))
        (dep_dir / "raw_xprompt.md").write_text("%w:foo proceed")

        target = _make_agent(
            cl_name="feature_a",
            raw_suffix="20260428100000",
            stop_time=datetime(2026, 4, 28, 12, 0, 0),
            agent_name="foo",
            artifacts_dir=str(tmp_path / "feature_a_artifacts"),
        )

        app = FakeDismissApp()
        app._agents_with_children = [target]

        patches = _patch_isolated_home(tmp_path)
        for p in patches:
            p.start()
        try:
            app._dismiss_done_agent(target)
            import asyncio

            callback, args = app._scheduled[0]
            asyncio.run(callback(*args))  # type: ignore[misc]
        finally:
            for p in patches:
                p.stop()

        # Disk references for the dependent agent were rewritten by the worker.
        assert json.loads((dep_dir / "agent_meta.json").read_text())["wait_for"] == [
            "260428.foo"
        ]
        assert (dep_dir / "raw_xprompt.md").read_text() == "%w:260428.foo proceed"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
