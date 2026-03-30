"""Tests for sase.agent.names module."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.agent.names import (
    claim_agent_name,
    find_named_agent,
    get_next_auto_name,
    is_workflow_complete,
)

# A PID that is guaranteed not to exist (beyond kernel PID_MAX_LIMIT)
_DEAD_PID = 99_999_999


def _make_agent(
    base: Path,
    project: str,
    suffix: str,
    name: str,
    *,
    done: bool = False,
    outcome: str | None = None,
    pid: int | None = None,
    appears_as_agent: bool | None = None,
    parent_timestamp: str | None = None,
    workflow_name: str | None = None,
) -> Path:
    """Create a fake agent artifact directory with agent_meta.json."""
    artifact_dir = (
        base / ".sase" / "projects" / project / "artifacts" / "ace-run" / suffix
    )
    artifact_dir.mkdir(parents=True)
    meta: dict[str, object] = {"name": name, "model": "test"}
    if pid is not None:
        meta["pid"] = pid
    if parent_timestamp is not None:
        meta["parent_timestamp"] = parent_timestamp
    if workflow_name is not None:
        meta["workflow_name"] = workflow_name
    (artifact_dir / "agent_meta.json").write_text(json.dumps(meta))
    if done:
        done_data: dict[str, object] = {}
        if outcome:
            done_data["outcome"] = outcome
        (artifact_dir / "done.json").write_text(json.dumps(done_data))
    if appears_as_agent is not None:
        wf_data: dict[str, object] = {
            "workflow_name": "test",
            "appears_as_agent": appears_as_agent,
        }
        (artifact_dir / "workflow_state.json").write_text(json.dumps(wf_data))
    return artifact_dir


class TestFindNamedAgent:
    def test_finds_done_agent(self, tmp_path: Path) -> None:
        _make_agent(tmp_path, "proj", "run1", "foo", done=True, outcome="success")
        with patch.object(Path, "home", return_value=tmp_path):
            result = find_named_agent("foo")
        assert result is not None
        assert result.is_done
        assert result.outcome == "success"

    def test_returns_none_when_not_found(self, tmp_path: Path) -> None:
        _make_agent(tmp_path, "proj", "run1", "foo")
        with patch.object(Path, "home", return_value=tmp_path):
            result = find_named_agent("bar")
        assert result is None

    def test_returns_none_when_no_projects_dir(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = find_named_agent("foo")
        assert result is None

    def test_prefers_running_over_done(self, tmp_path: Path) -> None:
        _make_agent(tmp_path, "proj", "run-old", "foo", done=True)
        running_dir = _make_agent(tmp_path, "proj", "run-new", "foo", pid=os.getpid())
        with patch.object(Path, "home", return_value=tmp_path):
            result = find_named_agent("foo")
        assert result is not None
        assert not result.is_done
        assert result.artifacts_dir == str(running_dir)

    def test_finds_agent_by_workflow_name(self, tmp_path: Path) -> None:
        """Resolves workflow name to the most recent done child agent."""
        _make_agent(tmp_path, "proj", "run1", "a.1", workflow_name="a", pid=_DEAD_PID)
        child_dir = _make_agent(
            tmp_path,
            "proj",
            "run2",
            "a.2",
            workflow_name="a",
            parent_timestamp="run1",
            done=True,
            outcome="completed",
        )
        with patch.object(Path, "home", return_value=tmp_path):
            result = find_named_agent("a")
        assert result is not None
        assert result.is_done
        assert result.outcome == "completed"
        assert result.artifacts_dir == str(child_dir)

    def test_exact_name_preferred_over_workflow(self, tmp_path: Path) -> None:
        """Exact name match takes priority over workflow_name match."""
        _make_agent(
            tmp_path,
            "proj",
            "run1",
            "a.1",
            workflow_name="a",
            done=True,
            outcome="completed",
        )
        exact_dir = _make_agent(
            tmp_path, "proj", "run2", "a", done=True, outcome="completed"
        )
        with patch.object(Path, "home", return_value=tmp_path):
            result = find_named_agent("a")
        assert result is not None
        assert result.artifacts_dir == str(exact_dir)

    def test_skips_dead_agent_without_done(self, tmp_path: Path) -> None:
        """Dead parent phases (no done.json, dead PID) are skipped."""
        _make_agent(tmp_path, "proj", "run-old", "foo", pid=_DEAD_PID)
        done_dir = _make_agent(
            tmp_path, "proj", "run-new", "foo", done=True, outcome="completed"
        )
        with patch.object(Path, "home", return_value=tmp_path):
            result = find_named_agent("foo")
        assert result is not None
        assert result.is_done
        assert result.outcome == "completed"
        assert result.artifacts_dir == str(done_dir)

    def test_only_done_skips_running(self, tmp_path: Path) -> None:
        """only_done=True skips running agents and returns done one."""
        _make_agent(tmp_path, "proj", "run-new", "foo", pid=os.getpid())
        done_dir = _make_agent(
            tmp_path, "proj", "run-old", "foo", done=True, outcome="completed"
        )
        with patch.object(Path, "home", return_value=tmp_path):
            result = find_named_agent("foo", only_done=True)
        assert result is not None
        assert result.is_done
        assert result.artifacts_dir == str(done_dir)

    def test_only_done_returns_none_when_no_done(self, tmp_path: Path) -> None:
        """only_done=True returns None when only running agents exist."""
        _make_agent(tmp_path, "proj", "run1", "foo", pid=os.getpid())
        with patch.object(Path, "home", return_value=tmp_path):
            result = find_named_agent("foo", only_done=True)
        assert result is None


class TestClaimAgentName:
    def test_preserves_done_agent_names(self, tmp_path: Path) -> None:
        """Completed agents keep their name when another agent claims it."""
        old_dir = _make_agent(tmp_path, "proj", "run-old", "foo", done=True)
        new_dir = _make_agent(tmp_path, "proj", "run-new", "foo")

        with patch.object(Path, "home", return_value=tmp_path):
            claim_agent_name("foo", str(new_dir))

        # Done agent should keep its name
        old_meta = json.loads((old_dir / "agent_meta.json").read_text())
        assert old_meta["name"] == "foo"

        # New agent keeps name too
        new_meta = json.loads((new_dir / "agent_meta.json").read_text())
        assert new_meta["name"] == "foo"

    def test_strips_name_from_stale_agents(self, tmp_path: Path) -> None:
        """Non-done agents (dead PID) still have their name stripped."""
        stale_dir = _make_agent(tmp_path, "proj", "run-old", "foo", pid=_DEAD_PID)
        new_dir = _make_agent(tmp_path, "proj", "run-new", "foo")

        with patch.object(Path, "home", return_value=tmp_path):
            claim_agent_name("foo", str(new_dir))

        # Stale agent should have name stripped
        stale_meta = json.loads((stale_dir / "agent_meta.json").read_text())
        assert "name" not in stale_meta
        assert stale_meta["model"] == "test"  # other fields preserved

        # New agent keeps name
        new_meta = json.loads((new_dir / "agent_meta.json").read_text())
        assert new_meta["name"] == "foo"

    def test_does_not_strip_different_name(self, tmp_path: Path) -> None:
        other_dir = _make_agent(tmp_path, "proj", "run-other", "bar")
        new_dir = _make_agent(tmp_path, "proj", "run-new", "foo")

        with patch.object(Path, "home", return_value=tmp_path):
            claim_agent_name("foo", str(new_dir))

        # "bar" agent should be untouched
        other_meta = json.loads((other_dir / "agent_meta.json").read_text())
        assert other_meta["name"] == "bar"

    def test_preserves_done_workflow_name_matches(self, tmp_path: Path) -> None:
        """Claiming a name preserves done agents with matching workflow_name."""
        child_dir = _make_agent(
            tmp_path,
            "proj",
            "run-old",
            "a.2",
            workflow_name="a",
            parent_timestamp="run-root",
            done=True,
        )
        new_dir = _make_agent(tmp_path, "proj", "run-new", "a")

        with patch.object(Path, "home", return_value=tmp_path):
            claim_agent_name("a", str(new_dir))

        # Done child keeps its workflow_name
        child_meta = json.loads((child_dir / "agent_meta.json").read_text())
        assert child_meta["workflow_name"] == "a"

        new_meta = json.loads((new_dir / "agent_meta.json").read_text())
        assert new_meta["name"] == "a"

    def test_no_projects_dir(self, tmp_path: Path) -> None:
        # Should not raise
        with patch.object(Path, "home", return_value=tmp_path):
            claim_agent_name("foo", "/nonexistent")


class TestGetNextAutoName:
    def test_returns_a_when_no_agents(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "a"

    def test_skips_active_names(self, tmp_path: Path) -> None:
        _make_agent(tmp_path, "proj", "run1", "a", pid=os.getpid())
        _make_agent(tmp_path, "proj", "run2", "b", pid=os.getpid())
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "c"

    def test_done_agent_holds_name(self, tmp_path: Path) -> None:
        """Done but not-dismissed agent keeps its name reserved."""
        _make_agent(tmp_path, "proj", "run1", "a", done=True)
        _make_agent(tmp_path, "proj", "run2", "b", pid=os.getpid())
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "c"

    def test_reuses_dismissed_agent_name(self, tmp_path: Path) -> None:
        """Name is freed once artifacts are deleted (dismissed)."""
        agent_dir = _make_agent(tmp_path, "proj", "run1", "a", done=True)
        _make_agent(tmp_path, "proj", "run2", "b", pid=os.getpid())

        # Simulate dismissal by removing the artifact directory
        import shutil

        shutil.rmtree(agent_dir)

        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "a"

    def test_wraps_to_double_letter(self, tmp_path: Path) -> None:
        for i, letter in enumerate("abcdefghijklmnopqrstuvwxyz"):
            _make_agent(tmp_path, "proj", f"run{i}", letter, pid=os.getpid())
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "aa"

    def test_reuses_name_of_dead_process(self, tmp_path: Path) -> None:
        """Agent without done.json but with a dead PID gets its name reused."""
        _make_agent(tmp_path, "proj", "run1", "a", pid=_DEAD_PID)
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "a"

    def test_reuses_name_when_no_pid(self, tmp_path: Path) -> None:
        """Agent without done.json and no PID info gets its name reused."""
        _make_agent(tmp_path, "proj", "run1", "a")
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "a"

    def test_workflow_without_appears_as_agent_holds_name(self, tmp_path: Path) -> None:
        """Workflows with appears_as_agent=False still reserve names."""
        _make_agent(tmp_path, "proj", "run1", "a", done=True, appears_as_agent=False)
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "b"

    def test_workflow_with_appears_as_agent_holds_name(self, tmp_path: Path) -> None:
        """Workflows with appears_as_agent=True hold names normally."""
        _make_agent(tmp_path, "proj", "run1", "a", done=True, appears_as_agent=True)
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "b"

    def test_mixed_workflow_and_agent_names(self, tmp_path: Path) -> None:
        """Both appears_as_agent=False and True workflows hold names."""
        _make_agent(tmp_path, "proj", "run1", "a", done=True, appears_as_agent=False)
        _make_agent(tmp_path, "proj", "run2", "b", done=True, appears_as_agent=True)
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "c"

    def test_workflow_name_reserves_base_name(self, tmp_path: Path) -> None:
        """Promoted initial agent reserves base workflow name, not child name."""
        _make_agent(tmp_path, "proj", "run1", "a.1", workflow_name="a", pid=os.getpid())
        with patch.object(Path, "home", return_value=tmp_path):
            # "a" should be reserved (via workflow_name), not "a.1"
            assert get_next_auto_name() == "b"

    def test_dismissed_suffix_does_not_hold_name(self, tmp_path: Path) -> None:
        """Dismissed agent suffixes are excluded from auto-name reservation."""
        _make_agent(tmp_path, "proj", "run1", "a", pid=os.getpid())
        _make_agent(tmp_path, "proj", "run2", "b", pid=os.getpid())
        dismissed_file = tmp_path / ".sase" / "dismissed_agents.json"
        dismissed_file.parent.mkdir(parents=True, exist_ok=True)
        dismissed_file.write_text('[["run", "proj", "run1"]]')
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch("sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE", dismissed_file),
        ):
            assert get_next_auto_name() == "a"


class TestIsWorkflowComplete:
    def test_no_workflow_agents_returns_none(self, tmp_path: Path) -> None:
        """Returns None when no agents have matching workflow_name."""
        _make_agent(tmp_path, "proj", "run1", "b", done=True)
        with patch.object(Path, "home", return_value=tmp_path):
            assert is_workflow_complete("a") is None

    def test_no_projects_dir_returns_none(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            assert is_workflow_complete("a") is None

    def test_root_alive_no_done(self, tmp_path: Path) -> None:
        """Root alive without done.json → False."""
        _make_agent(
            tmp_path,
            "proj",
            "run1",
            "a.1",
            workflow_name="a",
            pid=os.getpid(),
        )
        with patch.object(Path, "home", return_value=tmp_path):
            assert is_workflow_complete("a") is False

    def test_root_done_all_children_done(self, tmp_path: Path) -> None:
        """Root + coder both have done.json → True."""
        _make_agent(
            tmp_path,
            "proj",
            "run1",
            "a.1",
            workflow_name="a",
            pid=_DEAD_PID,
            done=True,
        )
        _make_agent(
            tmp_path,
            "proj",
            "run2",
            "a.2",
            workflow_name="a",
            parent_timestamp="run1",
            pid=_DEAD_PID,
            done=True,
        )
        with patch.object(Path, "home", return_value=tmp_path):
            assert is_workflow_complete("a") is True

    def test_root_done_child_alive(self, tmp_path: Path) -> None:
        """Root done but coder still alive without done.json → False."""
        _make_agent(
            tmp_path,
            "proj",
            "run1",
            "a.1",
            workflow_name="a",
            pid=_DEAD_PID,
            done=True,
        )
        _make_agent(
            tmp_path,
            "proj",
            "run2",
            "a.2",
            workflow_name="a",
            parent_timestamp="run1",
            pid=os.getpid(),
        )
        with patch.object(Path, "home", return_value=tmp_path):
            assert is_workflow_complete("a") is False

    def test_root_done_child_dead_no_done(self, tmp_path: Path) -> None:
        """Root done, intermediate child dead without done.json → True."""
        _make_agent(
            tmp_path,
            "proj",
            "run1",
            "a.1",
            workflow_name="a",
            pid=_DEAD_PID,
            done=True,
        )
        _make_agent(
            tmp_path,
            "proj",
            "run2",
            "a.2",
            workflow_name="a",
            parent_timestamp="run1",
            pid=_DEAD_PID,
        )
        with patch.object(Path, "home", return_value=tmp_path):
            assert is_workflow_complete("a") is True

    def test_root_dead_no_done_children_done(self, tmp_path: Path) -> None:
        """Root dead without done.json but all children done → True."""
        _make_agent(
            tmp_path,
            "proj",
            "run1",
            "a.1",
            workflow_name="a",
            pid=_DEAD_PID,
        )
        _make_agent(
            tmp_path,
            "proj",
            "run2",
            "a.2",
            workflow_name="a",
            parent_timestamp="run1",
            pid=_DEAD_PID,
            done=True,
        )
        with patch.object(Path, "home", return_value=tmp_path):
            assert is_workflow_complete("a") is True

    def test_root_dead_no_done_child_alive(self, tmp_path: Path) -> None:
        """Root dead without done.json, child still alive → False."""
        _make_agent(
            tmp_path,
            "proj",
            "run1",
            "a.1",
            workflow_name="a",
            pid=_DEAD_PID,
        )
        _make_agent(
            tmp_path,
            "proj",
            "run2",
            "a.2",
            workflow_name="a",
            parent_timestamp="run1",
            pid=os.getpid(),
        )
        with patch.object(Path, "home", return_value=tmp_path):
            assert is_workflow_complete("a") is False

    def test_root_dead_no_done_no_children(self, tmp_path: Path) -> None:
        """Root dead without done.json and no children → False."""
        _make_agent(
            tmp_path,
            "proj",
            "run1",
            "a.1",
            workflow_name="a",
            pid=_DEAD_PID,
        )
        with patch.object(Path, "home", return_value=tmp_path):
            assert is_workflow_complete("a") is False

    def test_single_root_with_done(self, tmp_path: Path) -> None:
        """Promoted root with no children yet, has done.json → True."""
        _make_agent(
            tmp_path,
            "proj",
            "run1",
            "a.1",
            workflow_name="a",
            pid=_DEAD_PID,
            done=True,
        )
        with patch.object(Path, "home", return_value=tmp_path):
            assert is_workflow_complete("a") is True

    def test_no_root_children_exist(self, tmp_path: Path) -> None:
        """Children exist but no root agent found → None."""
        _make_agent(
            tmp_path,
            "proj",
            "run2",
            "a.2",
            workflow_name="a",
            parent_timestamp="run1",
            pid=_DEAD_PID,
            done=True,
        )
        with patch.object(Path, "home", return_value=tmp_path):
            assert is_workflow_complete("a") is None


# ---------------------------------------------------------------------------
# extract_directives_and_write_meta: auto-dismiss behavior
# ---------------------------------------------------------------------------

_PHASES = "sase.axe.run_agent_phases"


def _mock_provider() -> MagicMock:
    p = MagicMock()
    p.resolve_model_name.return_value = "test-model"
    return p


def _run_extract(tmp_path: Path, *, env_auto_dismiss: bool = False) -> dict:
    """Call extract_directives_and_write_meta with standard mocks.

    Returns the written agent_meta.json as a dict.
    """
    from sase.axe.run_agent_phases import extract_directives_and_write_meta

    workspace = str(tmp_path / "workspace")
    artifacts = str(tmp_path / "artifacts")
    os.makedirs(workspace, exist_ok=True)
    os.makedirs(artifacts, exist_ok=True)

    env_patch: dict[str, str] = {}
    if env_auto_dismiss:
        env_patch["SASE_AGENT_AUTO_DISMISS"] = "1"

    with (
        patch.dict(os.environ, env_patch, clear=False),
        patch("sase.xprompt.process_xprompt_references", side_effect=lambda p, **kw: p),
        patch(
            "sase.llm_provider.registry.get_default_provider_name", return_value="test"
        ),
        patch("sase.llm_provider.registry.get_provider", return_value=_mock_provider()),
        patch(
            "sase.llm_provider.registry.resolve_model_provider",
            return_value=("test", "test-model"),
        ),
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
    ):
        # Remove the env var if not auto_dismiss (in case it leaked)
        if not env_auto_dismiss:
            os.environ.pop("SASE_AGENT_AUTO_DISMISS", None)
        info = extract_directives_and_write_meta("do stuff", workspace, artifacts)

    meta_path = os.path.join(artifacts, "agent_meta.json")
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            meta = json.load(f)
    else:
        meta = {}
    return {"info": info, "meta": meta}


class TestExtractDirectivesAutoDismiss:
    def test_skips_auto_name_when_auto_dismiss(self, tmp_path: Path) -> None:
        """Auto-dismiss agents should not get an auto-assigned name."""
        result = _run_extract(tmp_path, env_auto_dismiss=True)
        assert result["info"].name is None
        assert "name" not in result["meta"]

    def test_writes_hidden_when_auto_dismiss(self, tmp_path: Path) -> None:
        """Auto-dismiss agents should be marked hidden in agent_meta.json."""
        result = _run_extract(tmp_path, env_auto_dismiss=True)
        assert result["meta"].get("hidden") is True
        assert result["info"].hidden is True

    def test_normal_agent_gets_name(self, tmp_path: Path) -> None:
        """Without auto-dismiss, agents get an auto-assigned name."""
        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(tmp_path, env_auto_dismiss=False)
        assert result["info"].name is not None
        assert result["meta"].get("name") is not None

    def test_normal_agent_not_hidden(self, tmp_path: Path) -> None:
        """Without auto-dismiss, agents are not hidden."""
        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(tmp_path, env_auto_dismiss=False)
        assert result["meta"].get("hidden") is not True
        assert result["info"].hidden is False
