"""Tests for the split between persisted diff badges and live workspace hints.

The loader's status-override pass (``_apply_status_overrides``) classifies
only the *cheap* persisted diff badge (``diff_has_real_edits`` from a finalized
``diff_path``). The *expensive* live workspace pencil hint — a per-agent VCS
diff for active rows without a ``diff_path`` — must NOT run on the loader path
(it dominated startup). It is computed separately by
``classify_live_file_change_hint`` as deferred background work and left as
``None`` during the loader pass.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.tui.models.agent import Agent, AgentType, LinkedRepoMetadata
from sase.ace.tui.models.agent_loader import _apply_status_overrides
from sase.ace.tui.models._agent_status_overrides import (
    classify_live_file_change_hint,
)
from sase.ace.tui.widgets._agent_list_render_cache import agent_file_change_hint
from sase.ace.tui.widgets.file_panel import _diff as diff_mod
from sase.ace.tui.widgets.file_panel import _linked_deltas as linked_deltas_mod
from sase.linked_repos import record_opened_linked_repo


def _git_diff(path: str) -> str:
    return f"""diff --git a/{path} b/{path}
--- a/{path}
+++ b/{path}
@@ -1 +1 @@
-old
+new
"""


def _write_git_diff(path: Path, changed_path: str) -> None:
    path.write_text(_git_diff(changed_path), encoding="utf-8")


def _setup_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "myproj_1"
    (workspace / ".git").mkdir(parents=True)
    (workspace / ".git" / "index").write_bytes(b"\x00" * 16)
    return workspace


def _running_agent(workspace_dir: str) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my-feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 6, 15, 19, 0, 0),
        raw_suffix="20260615190000",
        workspace_dir=workspace_dir,
    )


def _root_plan_agent(*, diff_path: str | None = None) -> Agent:
    return Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my-feature",
        project_file="/tmp/test.sase",
        status="PLAN APPROVED",
        start_time=datetime(2026, 6, 15, 19, 0, 0),
        raw_suffix="20260615190000",
        role_suffix="-plan",
        plan_chain_root=True,
        diff_path=diff_path,
    )


def _active_coder_child(workspace_dir: str, *, diff_path: str | None = None) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my-feature-code",
        project_file="/tmp/test.sase",
        status="PLAN APPROVED",
        start_time=datetime(2026, 6, 15, 19, 30, 0),
        raw_suffix="20260615190000-code",
        parent_timestamp="20260615190000",
        role_suffix="-code",
        workspace_dir=workspace_dir,
        diff_path=diff_path,
    )


def _linked_repo(name: str, workspace_dir: Path) -> LinkedRepoMetadata:
    return LinkedRepoMetadata(
        name=name,
        workspace_dir=str(workspace_dir),
    )


class _DiffTextProvider:
    def __init__(self, diff_text: str) -> None:
        self.diff_text = diff_text

    def diff_with_untracked(self, cwd: str, *, timeout: int = 10):  # type: ignore[no-untyped-def]
        return (True, self.diff_text)


class _WorkspaceDiffProvider:
    def __init__(
        self,
        *,
        primary_diffs: dict[str, str],
        linked_diffs: dict[str, str],
    ) -> None:
        self.primary_diffs = primary_diffs
        self.linked_diffs = linked_diffs
        self.linked_has_changes_calls: list[str] = []
        self.linked_diff_calls: list[str] = []

    def diff_with_untracked(self, cwd: str, *, timeout: int = 10):  # type: ignore[no-untyped-def]
        del timeout
        if cwd in self.linked_diffs:
            self.linked_diff_calls.append(cwd)
            return (True, self.linked_diffs[cwd])
        return (True, self.primary_diffs.get(cwd, ""))

    def has_local_changes(self, cwd: str) -> tuple[bool, str | None]:
        self.linked_has_changes_calls.append(cwd)
        diff_text = self.linked_diffs.get(cwd, "")
        return (True, " M linked-file" if diff_text else None)


@pytest.fixture(autouse=True)
def _clear_linked_delta_caches() -> None:
    linked_deltas_mod._linked_diff_text_cache.clear()
    linked_deltas_mod._linked_delta_cache.clear()
    linked_deltas_mod._selected_agent_linked_delta_cache.clear()
    linked_deltas_mod._selected_agent_cache_monotonic.clear()


# --- loader pass must stay off the live VCS path -----------------------------


def test_loader_pass_skips_live_vcs_for_running_agent_without_diff_path(
    tmp_path: Path,
) -> None:
    """Regression: the status-override pass must never run a live VCS probe.

    Inlining the live hint here ran ``get_vcs_provider`` + ``diff_with_untracked``
    for hundreds of rows on the first agents load and dominated startup.
    """
    workspace = _setup_workspace(tmp_path)
    agent = _running_agent(str(workspace))

    with patch.object(diff_mod, "get_vcs_provider") as mock_get_provider:
        _apply_status_overrides([agent])

    mock_get_provider.assert_not_called()
    assert agent.diff_has_real_edits is None
    # Live hint stays unset on the loader pass; the deferred scan fills it in.
    assert agent.live_file_change_hint is None


def test_completed_diff_path_classification_stays_authoritative(
    tmp_path: Path,
) -> None:
    diff_path = tmp_path / "commit_diff.diff"
    _write_git_diff(diff_path, "sdd/plans/202606/change.md")
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my-feature",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 6, 15, 19, 0, 0),
        raw_suffix="20260615190000",
        diff_path=str(diff_path),
    )

    # The live VCS path must never run for a row with a persisted diff_path.
    with patch.object(diff_mod, "get_vcs_provider") as mock_get_provider:
        _apply_status_overrides([agent])

    assert agent.diff_has_real_edits is False
    assert agent.live_file_change_hint is None
    assert agent_file_change_hint(agent) is False
    mock_get_provider.assert_not_called()


def test_completed_linked_commit_diff_classification_renders_pencil(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "sase_7"
    linked = tmp_path / "sase-core_7"
    primary.mkdir()
    linked.mkdir()
    linked_diff = tmp_path / "linked.diff"
    _write_git_diff(linked_diff, "src/lib.rs")
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my-feature",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 6, 15, 19, 0, 0),
        raw_suffix="20260615190000",
        workspace_dir=str(primary),
        linked_repos=(_linked_repo("sase-core", linked),),
        step_output={
            "meta_commits": [
                {
                    "message": "feat: linked core",
                    "sha": "111111111111aaaa",
                    "cwd": str(linked),
                    "diff_path": str(linked_diff),
                },
            ],
        },
    )

    with patch.object(diff_mod, "get_vcs_provider") as mock_get_provider:
        _apply_status_overrides([agent])

    assert agent.diff_has_real_edits is None
    assert agent.linked_file_change_hint is True
    assert agent_file_change_hint(agent) is True
    mock_get_provider.assert_not_called()


def test_completed_linked_bookkeeping_diff_is_suppressed(tmp_path: Path) -> None:
    primary = tmp_path / "sase_7"
    linked = tmp_path / "sase-core_7"
    primary.mkdir()
    linked.mkdir()
    linked_diff = tmp_path / "linked.diff"
    _write_git_diff(linked_diff, "sdd/plans/202607/plan.md")
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my-feature",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 6, 15, 19, 0, 0),
        raw_suffix="20260615190000",
        workspace_dir=str(primary),
        linked_repos=(_linked_repo("sase-core", linked),),
        step_output={
            "meta_commits": [
                {
                    "message": "docs: linked plan",
                    "sha": "222222222222bbbb",
                    "cwd": str(linked),
                    "diff_path": str(linked_diff),
                },
            ],
        },
    )

    _apply_status_overrides([agent])

    assert agent.linked_file_change_hint is False
    assert agent_file_change_hint(agent) is False


def test_completed_linked_unreadable_diff_fails_open(tmp_path: Path) -> None:
    primary = tmp_path / "sase_7"
    linked = tmp_path / "sase-core_7"
    primary.mkdir()
    linked.mkdir()
    missing_diff = tmp_path / "missing.diff"
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my-feature",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 6, 15, 19, 0, 0),
        raw_suffix="20260615190000",
        workspace_dir=str(primary),
        linked_repos=(_linked_repo("sase-core", linked),),
        step_output={
            "meta_commits": [
                {
                    "message": "feat: linked core",
                    "sha": "333333333333cccc",
                    "cwd": str(linked),
                    "diff_path": str(missing_diff),
                },
            ],
        },
    )

    _apply_status_overrides([agent])

    assert agent.linked_file_change_hint is True
    assert agent_file_change_hint(agent) is True


# --- deferred live-hint helper -----------------------------------------------


def test_deferred_helper_classifies_real_workspace_edits_true(
    tmp_path: Path,
) -> None:
    diff_mod._diff_cache.clear()
    diff_mod._vcs_provider_cache.clear()
    workspace = _setup_workspace(tmp_path)
    agent = _running_agent(str(workspace))
    provider = _DiffTextProvider(_git_diff("src/app.py"))

    with patch.object(diff_mod.time, "time", return_value=1_700_000_000.0):
        with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
            hint = classify_live_file_change_hint(agent)

    assert hint is True
    agent.live_file_change_hint = hint
    assert agent_file_change_hint(agent) is True


def test_deferred_helper_classifies_bookkeeping_only_edits_false(
    tmp_path: Path,
) -> None:
    diff_mod._diff_cache.clear()
    diff_mod._vcs_provider_cache.clear()
    workspace = _setup_workspace(tmp_path)
    agent = _running_agent(str(workspace))
    provider = _DiffTextProvider(_git_diff("sdd/plans/202606/change.md"))

    with patch.object(diff_mod.time, "time", return_value=1_700_000_000.0):
        with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
            hint = classify_live_file_change_hint(agent)

    assert hint is False
    agent.live_file_change_hint = hint
    assert agent_file_change_hint(agent) is False


def test_deferred_helper_classifies_dirty_linked_workspace_true(
    tmp_path: Path,
) -> None:
    diff_mod._diff_cache.clear()
    diff_mod._vcs_provider_cache.clear()
    workspace = _setup_workspace(tmp_path)
    linked = tmp_path / "sase-core_1"
    linked.mkdir()
    agent = _running_agent(str(workspace))
    agent.linked_repos = (_linked_repo("sase-core", linked),)
    provider = _WorkspaceDiffProvider(
        primary_diffs={str(workspace): ""},
        linked_diffs={str(linked): _git_diff("src/lib.rs")},
    )

    with patch.object(diff_mod.time, "time", return_value=1_700_000_000.0):
        with patch.object(
            linked_deltas_mod.time,
            "time",
            return_value=1_700_000_000.0,
        ):
            with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
                hint = classify_live_file_change_hint(agent)

    assert hint is True
    assert provider.linked_has_changes_calls == [str(linked)]
    assert provider.linked_diff_calls == [str(linked)]


def test_deferred_helper_false_for_clean_linked_workspaces(
    tmp_path: Path,
) -> None:
    diff_mod._diff_cache.clear()
    diff_mod._vcs_provider_cache.clear()
    workspace = _setup_workspace(tmp_path)
    linked = tmp_path / "sase-core_1"
    linked.mkdir()
    agent = _running_agent(str(workspace))
    agent.linked_repos = (_linked_repo("sase-core", linked),)
    provider = _WorkspaceDiffProvider(
        primary_diffs={str(workspace): ""},
        linked_diffs={str(linked): ""},
    )

    with patch.object(diff_mod.time, "time", return_value=1_700_000_000.0):
        with patch.object(
            linked_deltas_mod.time,
            "time",
            return_value=1_700_000_000.0,
        ):
            with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
                hint = classify_live_file_change_hint(agent)

    assert hint is False
    assert provider.linked_has_changes_calls == [str(linked)]
    assert provider.linked_diff_calls == []


def test_deferred_helper_missing_linked_workspace_fails_closed(
    tmp_path: Path,
) -> None:
    diff_mod._diff_cache.clear()
    diff_mod._vcs_provider_cache.clear()
    workspace = _setup_workspace(tmp_path)
    missing_linked = tmp_path / "missing-core_1"
    agent = _running_agent(str(workspace))
    agent.linked_repos = (_linked_repo("sase-core", missing_linked),)
    provider = _WorkspaceDiffProvider(
        primary_diffs={str(workspace): ""},
        linked_diffs={},
    )

    with patch.object(diff_mod.time, "time", return_value=1_700_000_000.0):
        with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
            hint = classify_live_file_change_hint(agent)

    assert hint is False
    assert provider.linked_has_changes_calls == []


@pytest.mark.parametrize("status", ["PLAN DONE", "STOPPED", "FAILED (RETRIED)"])
def test_deferred_helper_skips_terminal_status_buckets(
    tmp_path: Path,
    status: str,
) -> None:
    diff_mod._diff_cache.clear()
    diff_mod._vcs_provider_cache.clear()
    workspace = _setup_workspace(tmp_path)
    agent = _running_agent(str(workspace))
    agent.status = status

    with patch.object(diff_mod, "get_vcs_provider") as mock_get_provider:
        hint = classify_live_file_change_hint(agent)

    assert hint is None
    mock_get_provider.assert_not_called()


def test_deferred_helper_skips_terminal_linked_workspace_probe(
    tmp_path: Path,
) -> None:
    diff_mod._diff_cache.clear()
    diff_mod._vcs_provider_cache.clear()
    workspace = _setup_workspace(tmp_path)
    linked = tmp_path / "sase-core_1"
    linked.mkdir()
    agent = _running_agent(str(workspace))
    agent.status = "DONE"
    agent.linked_repos = (_linked_repo("sase-core", linked),)

    with patch.object(diff_mod, "get_vcs_provider") as mock_get_provider:
        hint = classify_live_file_change_hint(agent)

    assert hint is None
    mock_get_provider.assert_not_called()


def test_deferred_helper_returns_none_for_persisted_diff_path() -> None:
    agent = _running_agent("/does/not/matter")
    agent.diff_path = "/tmp/sase/demo.diff"

    with patch.object(diff_mod, "get_vcs_provider") as mock_get_provider:
        hint = classify_live_file_change_hint(agent)

    assert hint is None
    mock_get_provider.assert_not_called()


def test_opened_workspace_record_only_is_eligible_for_live_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    linked = tmp_path / "sase-core_1"
    artifacts_dir.mkdir()
    linked.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    record_opened_linked_repo(
        "sase-core",
        str(linked),
        reason="inspect linked repo",
        opened_at="2026-07-07T16:00:00+00:00",
    )
    agent = _running_agent(str(tmp_path / "missing-primary"))
    agent.artifacts_dir = str(artifacts_dir)
    provider = _WorkspaceDiffProvider(
        primary_diffs={},
        linked_diffs={str(linked): _git_diff("src/lib.rs")},
    )

    monkeypatch.setattr(
        linked_deltas_mod,
        "resolve_vcs_provider_for_live_diff",
        lambda _workspace_dir: provider,
    )
    monkeypatch.setattr(
        linked_deltas_mod,
        "git_index_signature_for_live_diff",
        lambda _workspace_dir: None,
    )
    monkeypatch.setattr(linked_deltas_mod.time, "time", lambda: 1_700_000_000.0)

    hint = classify_live_file_change_hint(agent)

    assert hint is True
    assert provider.linked_has_changes_calls == [str(linked)]


def test_root_plan_uses_family_opened_workspace_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan_artifacts = tmp_path / "artifacts" / "plan"
    coder_artifacts = tmp_path / "artifacts" / "coder"
    linked = tmp_path / "sase-core_1"
    plan_artifacts.mkdir(parents=True)
    coder_artifacts.mkdir(parents=True)
    linked.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(coder_artifacts))
    record_opened_linked_repo(
        "sase-core",
        str(linked),
        reason="coder inspected core",
        opened_at="2026-07-07T16:00:00+00:00",
    )
    bookkeeping = tmp_path / "plan.diff"
    _write_git_diff(bookkeeping, "sdd/plans/202606/change.md")
    root = _root_plan_agent(diff_path=str(bookkeeping))
    root.artifacts_dir = str(plan_artifacts)
    child = _active_coder_child(str(tmp_path / "missing-child-primary"))
    child.artifacts_dir = str(coder_artifacts)
    root.followup_agents.append(child)
    provider = _WorkspaceDiffProvider(
        primary_diffs={},
        linked_diffs={str(linked): _git_diff("src/lib.rs")},
    )

    monkeypatch.setattr(
        linked_deltas_mod,
        "resolve_vcs_provider_for_live_diff",
        lambda _workspace_dir: provider,
    )
    monkeypatch.setattr(
        linked_deltas_mod,
        "git_index_signature_for_live_diff",
        lambda _workspace_dir: None,
    )
    monkeypatch.setattr(linked_deltas_mod.time, "time", lambda: 1_700_000_000.0)

    hint = classify_live_file_change_hint(root)

    assert hint is True
    assert provider.linked_has_changes_calls == [str(linked)]


# --- redirected root Plan rows -----------------------------------------------


def test_redirected_plan_row_uses_active_coder_live_edits(tmp_path: Path) -> None:
    """A plan row's bookkeeping diff_path must not suppress the child's hint.

    The detail panel sources a redirected root Plan row's diff from its active
    coder child. The deferred hint must classify the *child* workspace even
    when the plan row carries its own bookkeeping-only diff_path, so the row
    badge matches the detail panel's ``Deltas:``.
    """
    diff_mod._diff_cache.clear()
    diff_mod._vcs_provider_cache.clear()
    child_workspace = _setup_workspace(tmp_path)
    bookkeeping = tmp_path / "plan.diff"
    _write_git_diff(bookkeeping, "sdd/plans/202606/change.md")
    root = _root_plan_agent(diff_path=str(bookkeeping))
    root.followup_agents.append(_active_coder_child(str(child_workspace)))
    provider = _DiffTextProvider(_git_diff("src/app.py"))

    with patch.object(diff_mod.time, "time", return_value=1_700_000_000.0):
        with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
            hint = classify_live_file_change_hint(root)

    assert hint is True
    root.live_file_change_hint = hint
    assert agent_file_change_hint(root) is True


def test_redirected_plan_row_false_for_bookkeeping_only_child_edits(
    tmp_path: Path,
) -> None:
    diff_mod._diff_cache.clear()
    diff_mod._vcs_provider_cache.clear()
    child_workspace = _setup_workspace(tmp_path)
    bookkeeping = tmp_path / "plan.diff"
    _write_git_diff(bookkeeping, "sdd/plans/202606/change.md")
    root = _root_plan_agent(diff_path=str(bookkeeping))
    root.followup_agents.append(_active_coder_child(str(child_workspace)))
    provider = _DiffTextProvider(_git_diff("sdd/plans/202606/notes.md"))

    with patch.object(diff_mod.time, "time", return_value=1_700_000_000.0):
        with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
            hint = classify_live_file_change_hint(root)

    assert hint is False
    root.live_file_change_hint = hint
    assert agent_file_change_hint(root) is False


def test_redirected_plan_row_skips_live_path_when_child_has_diff_path(
    tmp_path: Path,
) -> None:
    """A child with its own persisted diff stays authoritative — no VCS probe."""
    diff_mod._diff_cache.clear()
    diff_mod._vcs_provider_cache.clear()
    child_diff = tmp_path / "child.diff"
    _write_git_diff(child_diff, "src/app.py")
    bookkeeping = tmp_path / "plan.diff"
    _write_git_diff(bookkeeping, "sdd/plans/202606/change.md")
    root = _root_plan_agent(diff_path=str(bookkeeping))
    root.followup_agents.append(
        _active_coder_child("/does/not/matter", diff_path=str(child_diff))
    )

    with patch.object(diff_mod, "get_vcs_provider") as mock_get_provider:
        hint = classify_live_file_change_hint(root)

    assert hint is None
    mock_get_provider.assert_not_called()


def test_non_redirected_plan_row_with_diff_path_skips_live_path(
    tmp_path: Path,
) -> None:
    """A plan row with no active coder child is not redirected — diff_path wins."""
    diff_mod._diff_cache.clear()
    diff_mod._vcs_provider_cache.clear()
    bookkeeping = tmp_path / "plan.diff"
    _write_git_diff(bookkeeping, "src/app.py")
    root = _root_plan_agent(diff_path=str(bookkeeping))

    with patch.object(diff_mod, "get_vcs_provider") as mock_get_provider:
        hint = classify_live_file_change_hint(root)

    assert hint is None
    mock_get_provider.assert_not_called()
