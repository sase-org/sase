"""Bundle-path resolution behavior of the saved-group record builder.

These lock the perf contract from
``sdd/plans/202606/recent_restore_perf_fix.md``: the optimistic UI-thread build
must not probe the filesystem for dismissed bundles, while off-UI-thread callers
keep the disk-resolving default.
"""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.actions.agents._recent_dismissal_groups import (
    build_recent_dismissed_agent_group,
)
from sase.ace.tui.actions.agents._saved_group_records import build_saved_agent_group

from tests.ace.tui._agent_marking_helpers import _make_agent

_PROBE = "sase.ace.dismissed_agents.dismissed_bundle_path_for_agent"


def test_resolve_bundle_paths_false_skips_disk_probe() -> None:
    """The optimistic UI-thread build must not touch the filesystem."""
    agent = _make_agent(raw_suffix="20240101120000")

    with patch(_PROBE) as mock_probe:
        group = build_saved_agent_group([agent], resolve_bundle_paths=False)

    mock_probe.assert_not_called()
    assert group.agent_refs[0].bundle_path is None


def test_resolve_bundle_paths_false_honors_in_memory_path() -> None:
    """A revived-then-re-dismissed agent keeps its cached bundle path."""
    agent = _make_agent(
        raw_suffix="20240101120000",
        _dismissed_bundle_path="/bundles/202401/agent.json",
    )

    with patch(_PROBE) as mock_probe:
        group = build_saved_agent_group([agent], resolve_bundle_paths=False)

    mock_probe.assert_not_called()
    assert group.agent_refs[0].bundle_path == "/bundles/202401/agent.json"


def test_recent_dismissed_group_build_skips_disk_probe() -> None:
    """The recent-dismissal builder feeds the hot dismiss/kill paths I/O-free."""
    agent = _make_agent(raw_suffix="20240101120000")

    with patch(_PROBE) as mock_probe:
        group = build_recent_dismissed_agent_group([agent])

    mock_probe.assert_not_called()
    assert group is not None
    assert group.source == "recent_dismissal"
    assert group.agent_refs[0].bundle_path is None


def test_saved_group_captures_normalized_truncated_prompt_preview() -> None:
    agent = _make_agent(raw_suffix="20240101120000")
    prompt = "  Review\n\n" + ("backend " * 30) + "cleanup  "
    agent.__dict__["get_raw_xprompt_content"] = lambda: prompt

    group = build_saved_agent_group([agent], resolve_bundle_paths=False)

    preview = group.agent_refs[0].prompt_preview
    assert preview is not None
    assert "\n" not in preview
    assert len(preview) == 120
    assert preview.endswith("...")
    assert preview.startswith("Review backend backend")


def test_saved_group_prompt_preview_missing_or_failing_is_none() -> None:
    missing = _make_agent(raw_suffix="20240101120000")
    missing.__dict__["get_raw_xprompt_content"] = lambda: None
    failing = _make_agent(raw_suffix="20240101120001")

    def fail_read() -> str | None:
        raise OSError("prompt cache unavailable")

    failing.__dict__["get_raw_xprompt_content"] = fail_read

    group = build_saved_agent_group(
        [missing, failing],
        resolve_bundle_paths=False,
    )

    assert [ref.prompt_preview for ref in group.agent_refs] == [None, None]


def test_saved_group_title_uses_top_level_count_for_single_tribe() -> None:
    group = build_saved_agent_group(
        [
            _make_agent(tribe="backend", raw_suffix="20240101120000"),
            _make_agent(
                tribe="backend",
                raw_suffix="20240101120001",
                parent_timestamp="20240101120000",
            ),
        ],
        resolve_bundle_paths=False,
    )

    assert group.agent_count == 2
    assert group.top_level_agent_count == 1
    assert group.title == "1 agent from @backend"


def test_saved_group_title_uses_top_level_count_for_single_pr() -> None:
    group = build_saved_agent_group(
        [
            _make_agent(cl_name="backend", raw_suffix="20240101120000"),
            _make_agent(
                cl_name="backend",
                raw_suffix="20240101120001",
                parent_timestamp="20240101120000",
            ),
            _make_agent(cl_name="backend", raw_suffix="20240101120002"),
        ],
        resolve_bundle_paths=False,
    )

    assert group.agent_count == 3
    assert group.top_level_agent_count == 2
    assert group.title == "2 agents in backend"


def test_saved_group_title_uses_top_level_count_for_single_project() -> None:
    group = build_saved_agent_group(
        [
            _make_agent(
                cl_name="unknown",
                project_file="/tmp/projects/sase/sase.gp",
                raw_suffix="20240101120000",
            ),
            _make_agent(
                cl_name="unknown",
                project_file="/tmp/projects/sase/sase.gp",
                raw_suffix="20240101120001",
                parent_timestamp="20240101120000",
            ),
            _make_agent(
                cl_name="unknown",
                project_file="/tmp/projects/sase/sase.gp",
                raw_suffix="20240101120002",
            ),
        ],
        resolve_bundle_paths=False,
    )

    assert group.agent_count == 3
    assert group.top_level_agent_count == 2
    assert group.title == "2 agents from sase"


def test_saved_group_title_uses_top_level_count_across_prs() -> None:
    group = build_saved_agent_group(
        [
            _make_agent(
                cl_name="backend",
                project_file="/tmp/projects/backend/backend.sase",
                raw_suffix="20240101120000",
            ),
            _make_agent(
                cl_name="frontend",
                project_file="/tmp/projects/frontend/frontend.sase",
                raw_suffix="20240101120001",
            ),
            _make_agent(
                cl_name="backend",
                project_file="/tmp/projects/backend/backend.sase",
                raw_suffix="20240101120002",
                parent_timestamp="20240101120000",
            ),
        ],
        resolve_bundle_paths=False,
    )

    assert group.agent_count == 3
    assert group.top_level_agent_count == 2
    assert group.title == "2 agents across 2 PRs"


def test_saved_group_title_uses_top_level_count_for_bare_title() -> None:
    group = build_saved_agent_group(
        [
            _make_agent(
                cl_name="unknown",
                project_file="",
                raw_suffix="20240101120000",
            ),
            _make_agent(
                cl_name="unknown",
                project_file="",
                raw_suffix="20240101120001",
                parent_timestamp="20240101120000",
            ),
        ],
        resolve_bundle_paths=False,
    )

    assert group.agent_count == 2
    assert group.top_level_agent_count == 1
    assert group.title == "1 agent"


def test_resolve_bundle_paths_default_uses_helper() -> None:
    """Default (True) preserves disk resolution for off-UI-thread callers."""
    agent = _make_agent(raw_suffix="20240101120000")

    with patch(_PROBE, return_value="/bundles/202401/resolved.json") as mock_probe:
        group = build_saved_agent_group([agent])

    mock_probe.assert_called_once()
    assert group.agent_refs[0].bundle_path == "/bundles/202401/resolved.json"
