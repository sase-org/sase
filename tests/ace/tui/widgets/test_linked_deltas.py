"""Tests for linked-repository delta computation."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from sase.ace.changespec.models import DeltaEntry, DeltaLineStats
from sase.ace.tui.models.agent import Agent, AgentType, LinkedRepoMetadata
from sase.ace.tui.widgets.file_panel import _linked_deltas as linked_deltas_mod


class _FakeLinkedDiffProvider:
    def __init__(
        self,
        *,
        changes_by_workspace: dict[str, str | None],
        diff_by_workspace: dict[str, str],
    ) -> None:
        self.changes_by_workspace = changes_by_workspace
        self.diff_by_workspace = diff_by_workspace
        self.has_changes_calls: list[str] = []
        self.diff_calls: list[str] = []

    def has_local_changes(self, cwd: str) -> tuple[bool, str | None]:
        self.has_changes_calls.append(cwd)
        return (True, self.changes_by_workspace.get(cwd))

    def diff_with_untracked(
        self,
        cwd: str,
        *,
        timeout: int = 10,
    ) -> tuple[bool, str | None]:
        del timeout
        self.diff_calls.append(cwd)
        return (True, self.diff_by_workspace.get(cwd, ""))


@pytest.fixture(autouse=True)
def _clear_linked_delta_caches() -> None:
    linked_deltas_mod._linked_delta_cache.clear()
    linked_deltas_mod._selected_agent_linked_delta_cache.clear()
    linked_deltas_mod._selected_agent_cache_monotonic.clear()


def _agent(
    *,
    status: str = "RUNNING",
    linked_repos: tuple[LinkedRepoMetadata, ...] = (),
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="linked-deltas",
        project_file="/tmp/linked-deltas.sase",
        status=status,
        start_time=datetime(2026, 6, 20, 12, 0),
        raw_suffix="20260620120000",
        linked_repos=linked_repos,
    )


def _repo(
    name: str,
    workspace_dir: Path,
    *,
    strategy: str = "suffix",
) -> LinkedRepoMetadata:
    return LinkedRepoMetadata(
        name=name,
        workspace_dir=str(workspace_dir),
        workspace_strategy=strategy,
    )


def _patch_provider(
    monkeypatch: pytest.MonkeyPatch,
    provider: _FakeLinkedDiffProvider,
    *,
    wall_time: float = 1_700_000_000.0,
    monotonic: float = 50.0,
) -> None:
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
    monkeypatch.setattr(linked_deltas_mod.time, "time", lambda: wall_time)
    monkeypatch.setattr(linked_deltas_mod.time, "monotonic", lambda: monotonic)


def test_compute_linked_delta_groups_filters_and_dedupes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = tmp_path / "sase-core"
    nvim = tmp_path / "sase-nvim"
    static = tmp_path / "static"
    clean = tmp_path / "clean"
    for path in (core, nvim, static, clean):
        path.mkdir()
    missing = tmp_path / "missing"
    provider = _FakeLinkedDiffProvider(
        changes_by_workspace={
            str(core): " M crates/core/src/lib.rs",
            str(nvim): "?? plugin.lua",
            str(static): " M ignored.py",
            str(clean): None,
        },
        diff_by_workspace={
            str(core): """diff --git a/crates/core/src/lib.rs b/crates/core/src/lib.rs
--- a/crates/core/src/lib.rs
+++ b/crates/core/src/lib.rs
@@ -1 +1,2 @@
 old
+new
""",
            str(nvim): """diff --git a/plugin.lua b/plugin.lua
new file mode 100644
--- /dev/null
+++ b/plugin.lua
@@ -0,0 +1 @@
+vim.g.sase = true
""",
        },
    )
    _patch_provider(monkeypatch, provider)
    agent = _agent(
        linked_repos=(
            _repo("sase-core", core),
            _repo("sase-static", static, strategy="none"),
            _repo("sase-missing", missing),
            _repo("sase-clean", clean),
            _repo("sase-core", core),
            _repo("sase-nvim", nvim),
        )
    )

    groups = linked_deltas_mod.compute_linked_delta_groups(agent)

    assert [group.repo_name for group in groups] == ["sase-core", "sase-nvim"]
    assert groups[0].entries == (
        DeltaEntry(
            path="crates/core/src/lib.rs",
            change_type="M",
            line_stats=DeltaLineStats(added=1),
        ),
    )
    assert groups[1].entries == (
        DeltaEntry(
            path="plugin.lua",
            change_type="A",
            line_stats=DeltaLineStats(added=1),
        ),
    )
    assert provider.has_changes_calls == [str(core), str(clean), str(nvim)]
    assert provider.diff_calls == [str(core), str(nvim)]
    assert linked_deltas_mod.get_cached_linked_delta_groups(agent) == groups


def test_compute_linked_delta_groups_skips_terminal_agents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = tmp_path / "sase-core"
    core.mkdir()

    def fail_provider(_workspace_dir: str) -> Any:
        raise AssertionError("terminal agent should not probe linked repos")

    monkeypatch.setattr(
        linked_deltas_mod,
        "resolve_vcs_provider_for_live_diff",
        fail_provider,
    )
    agent = _agent(status="DONE", linked_repos=(_repo("sase-core", core),))
    linked_deltas_mod._selected_agent_linked_delta_cache[agent.identity] = (
        linked_deltas_mod.LinkedDeltaGroup(
            repo_name="sase-core",
            workspace_dir=str(core),
            entries=(DeltaEntry(path="stale.py", change_type="M"),),
        ),
    )

    assert linked_deltas_mod.compute_linked_delta_groups(agent) == ()
    assert linked_deltas_mod.get_cached_linked_delta_groups(agent) == ()


def test_should_refresh_linked_delta_groups_is_memory_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = tmp_path / "sase-core"
    core.mkdir()
    agent = _agent(linked_repos=(_repo("sase-core", core),))
    provider = _FakeLinkedDiffProvider(
        changes_by_workspace={str(core): None},
        diff_by_workspace={},
    )
    _patch_provider(monkeypatch, provider, monotonic=10.0)

    assert linked_deltas_mod.should_refresh_linked_delta_groups(agent) is True
    assert linked_deltas_mod.compute_linked_delta_groups(agent) == ()
    assert linked_deltas_mod.should_refresh_linked_delta_groups(agent) is False

    monkeypatch.setattr(linked_deltas_mod.time, "monotonic", lambda: 12.0)
    assert linked_deltas_mod.should_refresh_linked_delta_groups(agent) is True
