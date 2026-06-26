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

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import _apply_status_overrides
from sase.ace.tui.models._agent_status_overrides import (
    classify_live_file_change_hint,
)
from sase.ace.tui.widgets._agent_list_render_cache import agent_file_change_hint
from sase.ace.tui.widgets.file_panel import _diff as diff_mod


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


class _DiffTextProvider:
    def __init__(self, diff_text: str) -> None:
        self.diff_text = diff_text

    def diff_with_untracked(self, cwd: str, *, timeout: int = 10):  # type: ignore[no-untyped-def]
        return (True, self.diff_text)


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
    _write_git_diff(diff_path, "sdd/tales/202606/change.md")
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
    provider = _DiffTextProvider(_git_diff("sdd/tales/202606/change.md"))

    with patch.object(diff_mod.time, "time", return_value=1_700_000_000.0):
        with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
            hint = classify_live_file_change_hint(agent)

    assert hint is False
    agent.live_file_change_hint = hint
    assert agent_file_change_hint(agent) is False


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


def test_deferred_helper_returns_none_for_persisted_diff_path() -> None:
    agent = _running_agent("/does/not/matter")
    agent.diff_path = "/tmp/sase/demo.diff"

    with patch.object(diff_mod, "get_vcs_provider") as mock_get_provider:
        hint = classify_live_file_change_hint(agent)

    assert hint is None
    mock_get_provider.assert_not_called()


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
    _write_git_diff(bookkeeping, "sdd/tales/202606/change.md")
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
    _write_git_diff(bookkeeping, "sdd/tales/202606/change.md")
    root = _root_plan_agent(diff_path=str(bookkeeping))
    root.followup_agents.append(_active_coder_child(str(child_workspace)))
    provider = _DiffTextProvider(_git_diff("sdd/tales/202606/notes.md"))

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
    _write_git_diff(bookkeeping, "sdd/tales/202606/change.md")
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
