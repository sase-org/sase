"""Selection narrows a snapshot to the rows a provider drain can act on."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sase.agent._drain_selection import select_drain_candidates
from sase.agent.running_listing import RunningAgentInfo
from sase.llm_provider.provider_disable import TemporaryProviderDisable
from tests._agent_names_fixtures import make_agent

_DISABLE = TemporaryProviderDisable(
    version=2,
    provider="claude",
    created_at=1_800_000_000.0,
    expires_at=None,
    source="test",
    mode="hard",
)


def _row(
    artifacts_dir: Path,
    *,
    name: str | None = "02p",
    status: str = "RUNNING",
    provider: str | None = "claude",
    agent_family_role: str | None = None,
    role_suffix: str | None = None,
) -> RunningAgentInfo:
    return RunningAgentInfo(
        name=name,
        project="gh_sase-org__sase",
        pid=1234,
        model="opus",
        provider=provider,
        workspace_num=1,
        duration="2m",
        approve=False,
        status=status,
        artifacts_dir=str(artifacts_dir),
        agent_family_role=agent_family_role,
        role_suffix=role_suffix,
    )


def _failed_dir(
    tmp_path: Path,
    *,
    name: str = "02p",
    suffix: str = "20260818130000",
    finished_at: float,
    error: str = "usage limit reached",
    exec_llm_provider: str | None = None,
) -> Path:
    extra_meta: dict[str, object] | None = (
        {"exec_llm_provider": exec_llm_provider} if exec_llm_provider else None
    )
    artifacts_dir = make_agent(
        tmp_path,
        "gh_sase-org__sase",
        suffix,
        name,
        done=True,
        outcome="failed",
        extra_meta=extra_meta,
    )
    done = json.loads((artifacts_dir / "done.json").read_text())
    done["finished_at"] = finished_at
    done["error"] = error
    (artifacts_dir / "done.json").write_text(json.dumps(done))
    return artifacts_dir


def test_selects_live_row_matching_provider(tmp_path: Path) -> None:
    artifacts_dir = make_agent(tmp_path, "gh_sase-org__sase", "20260818120000", "02p")
    row = _row(artifacts_dir, status="RUNNING")
    with patch("sase.agent.identity.discover_agent_identity", return_value=None):
        candidates, skips = select_drain_candidates([row], "claude", _DISABLE)
    assert [c.name for c in candidates] == ["02p"]
    assert skips == []


def test_ignores_row_on_a_different_provider(tmp_path: Path) -> None:
    artifacts_dir = make_agent(tmp_path, "gh_sase-org__sase", "20260818120000", "02p")
    row = _row(artifacts_dir, status="RUNNING", provider="codex")
    with patch("sase.agent.identity.discover_agent_identity", return_value=None):
        candidates, skips = select_drain_candidates([row], "claude", _DISABLE)
    assert candidates == []
    assert skips == []


def test_exec_llm_provider_overrides_listed_provider(tmp_path: Path) -> None:
    artifacts_dir = make_agent(
        tmp_path,
        "gh_sase-org__sase",
        "20260818120000",
        "02p",
        extra_meta={"exec_llm_provider": "claude"},
    )
    # The listing's own provider field says "codex", but the meta marker
    # records the effective execution provider as "claude".
    row = _row(artifacts_dir, status="RUNNING", provider="codex")
    with patch("sase.agent.identity.discover_agent_identity", return_value=None):
        candidates, _ = select_drain_candidates([row], "claude", _DISABLE)
    assert [c.name for c in candidates] == ["02p"]


def test_recently_failed_row_within_grace_and_matching_provider_is_selected(
    tmp_path: Path,
) -> None:
    artifacts_dir = _failed_dir(
        tmp_path, finished_at=_DISABLE.created_at - 60, exec_llm_provider="claude"
    )
    row = _row(artifacts_dir, status="FAILED", provider="claude")
    with (
        patch("sase.agent.identity.discover_agent_identity", return_value=None),
        patch(
            "sase.llm_provider.usage_limit_config.detect_usage_limit",
            return_value=object(),
        ),
    ):
        candidates, skips = select_drain_candidates([row], "claude", _DISABLE)
    assert [c.name for c in candidates] == ["02p"]
    assert skips == []


def test_failed_row_outside_grace_window_is_not_selected(tmp_path: Path) -> None:
    artifacts_dir = _failed_dir(
        tmp_path,
        finished_at=_DISABLE.created_at - 301,
        exec_llm_provider="claude",
    )
    row = _row(artifacts_dir, status="FAILED", provider="claude")
    with (
        patch("sase.agent.identity.discover_agent_identity", return_value=None),
        patch(
            "sase.llm_provider.usage_limit_config.detect_usage_limit",
            return_value=object(),
        ),
    ):
        candidates, skips = select_drain_candidates([row], "claude", _DISABLE)
    assert candidates == []
    assert skips == []


def test_failed_row_at_exact_grace_boundary_is_selected(tmp_path: Path) -> None:
    artifacts_dir = _failed_dir(
        tmp_path,
        finished_at=_DISABLE.created_at - 300,
        exec_llm_provider="claude",
    )
    row = _row(artifacts_dir, status="FAILED", provider="claude")
    with (
        patch("sase.agent.identity.discover_agent_identity", return_value=None),
        patch(
            "sase.llm_provider.usage_limit_config.detect_usage_limit",
            return_value=object(),
        ),
    ):
        candidates, _ = select_drain_candidates([row], "claude", _DISABLE)
    assert [c.name for c in candidates] == ["02p"]


def test_failed_row_whose_error_does_not_match_usage_limit_is_not_selected(
    tmp_path: Path,
) -> None:
    artifacts_dir = _failed_dir(
        tmp_path,
        finished_at=_DISABLE.created_at - 60,
        error="some unrelated crash",
        exec_llm_provider="claude",
    )
    row = _row(artifacts_dir, status="FAILED", provider="claude")
    with (
        patch("sase.agent.identity.discover_agent_identity", return_value=None),
        patch(
            "sase.llm_provider.usage_limit_config.detect_usage_limit",
            return_value=None,
        ),
    ):
        candidates, skips = select_drain_candidates([row], "claude", _DISABLE)
    assert candidates == []
    assert skips == []


def test_monitor_member_is_dropped_and_reported(tmp_path: Path) -> None:
    artifacts_dir = make_agent(tmp_path, "gh_sase-org__sase", "20260818120000", "02p")
    row = _row(artifacts_dir, status="RUNNING", agent_family_role="monitor")
    with patch("sase.agent.identity.discover_agent_identity", return_value=None):
        candidates, skips = select_drain_candidates([row], "claude", _DISABLE)
    assert candidates == []
    assert [s.reason for s in skips] == ["monitor"]
    assert skips[0].name == "02p"


def test_pending_question_row_is_dropped_and_reported(tmp_path: Path) -> None:
    artifacts_dir = make_agent(tmp_path, "gh_sase-org__sase", "20260818120000", "02p")
    row = _row(artifacts_dir, status="QUESTION")
    with patch("sase.agent.identity.discover_agent_identity", return_value=None):
        candidates, skips = select_drain_candidates([row], "claude", _DISABLE)
    assert candidates == []
    assert [s.reason for s in skips] == ["pending_question"]


def test_caller_agent_is_dropped_and_reported(tmp_path: Path) -> None:
    artifacts_dir = make_agent(tmp_path, "gh_sase-org__sase", "20260818120000", "02p")
    row = _row(artifacts_dir, status="RUNNING")
    identity = SimpleNamespace(name="02p")
    with patch("sase.agent.identity.discover_agent_identity", return_value=identity):
        candidates, skips = select_drain_candidates([row], "claude", _DISABLE)
    assert candidates == []
    assert [s.reason for s in skips] == ["caller"]


def test_orders_least_progress_first_and_preserves_ties(tmp_path: Path) -> None:
    rows = []
    for index, status in enumerate(["RUNNING", "STARTING", "FAILED", "WAITING"]):
        artifacts_dir = make_agent(
            tmp_path,
            "gh_sase-org__sase",
            f"2026081812000{index}",
            f"agent{index}",
        )
        if status == "FAILED":
            artifacts_dir = _failed_dir(
                tmp_path,
                name=f"agent{index}",
                suffix=f"2026081813000{index}",
                finished_at=_DISABLE.created_at - 10,
                exec_llm_provider="claude",
            )
        rows.append(_row(artifacts_dir, status=status, name=f"agent{index}"))
    # A second WAITING row to prove ties keep the snapshot's own order.
    extra_dir = make_agent(
        tmp_path, "gh_sase-org__sase", "20260818120099", "agent-extra-waiting"
    )
    rows.append(_row(extra_dir, status="WAITING", name="agent-extra-waiting"))

    with (
        patch("sase.agent.identity.discover_agent_identity", return_value=None),
        patch(
            "sase.llm_provider.usage_limit_config.detect_usage_limit",
            return_value=object(),
        ),
    ):
        candidates, _ = select_drain_candidates(rows, "claude", _DISABLE)

    assert [c.name for c in candidates] == [
        "agent3",
        "agent-extra-waiting",
        "agent1",
        "agent2",
        "agent0",
    ]


def test_unnamed_row_is_silently_excluded(tmp_path: Path) -> None:
    artifacts_dir = make_agent(tmp_path, "gh_sase-org__sase", "20260818120000", "02p")
    row = _row(artifacts_dir, status="RUNNING", name=None)
    with patch("sase.agent.identity.discover_agent_identity", return_value=None):
        candidates, skips = select_drain_candidates([row], "claude", _DISABLE)
    assert candidates == []
    assert skips == []
