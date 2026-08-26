"""Coverage tests for the `chop-agent` projection rule."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.artifact_links.projection._chop_agent import project_chop_agent_rows
from sase.artifact_links.projection._model import ProjectionInputs
from sase.axe._config_types import AxeConfig, ChopConfig, LumberjackConfig
from tests._conftest_environment import redirect_sase_home


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")


def _fixture_axe_config() -> AxeConfig:
    return AxeConfig(
        lumberjacks={
            "refresh_docs": LumberjackConfig(
                name="refresh_docs",
                description="",
                interval=60,
                chops=[
                    ChopConfig(
                        name="refresh_docs[sase]",
                        description="",
                        base_name="refresh_docs",
                        target_key="sase",
                    ),
                ],
            ),
            "hooks": LumberjackConfig(
                name="hooks",
                description="",
                interval=60,
                chops=[
                    ChopConfig(name="hook_checks", description="", enabled=False),
                ],
            ),
        }
    )


def _patch_axe_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.axe.config.load_axe_config", _fixture_axe_config, raising=True
    )


def _mkagent(agents_dir: Path, name: str) -> None:
    (agents_dir / name).mkdir(parents=True)


def _inputs(root: Path | None) -> ProjectionInputs:
    return ProjectionInputs(
        project_key="gh_sase-org__sase",
        primary_repo_root=None,
        primary_repo_name=None,
        agents_sidecar_root=root,
    )


def test_resolves_a_for_each_expanded_chop_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_axe_config(monkeypatch)
    root = tmp_path / "agents-sidecar"
    agents_dir = root / "agents"
    _mkagent(agents_dir, "bbugyi.athena.chop.refresh_docs.sase.0_123456.1")

    edges = project_chop_agent_rows(_inputs(root))

    assert len(edges) == 1
    edge = edges[0]
    assert edge.source_ref == "chop:refresh_docs/refresh_docs"
    assert edge.relation == "launched"
    assert edge.target_ref == "agent:bbugyi.athena.chop.refresh_docs.sase.0_123456.1"
    assert edge.rule_id == "chop-agent"


def test_a_disabled_chop_still_resolves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_axe_config(monkeypatch)
    root = tmp_path / "agents-sidecar"
    agents_dir = root / "agents"
    _mkagent(agents_dir, "bbugyi.athena.chop.hook_checks.7_000001.2")

    edges = project_chop_agent_rows(_inputs(root))

    assert len(edges) == 1
    assert edges[0].source_ref == "chop:hooks/hook_checks"


def test_an_agent_name_with_no_chop_segment_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_axe_config(monkeypatch)
    root = tmp_path / "agents-sidecar"
    agents_dir = root / "agents"
    _mkagent(agents_dir, "bbugyi.athena.9w")

    assert project_chop_agent_rows(_inputs(root)) == ()


def test_a_chop_segment_that_does_not_resolve_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_axe_config(monkeypatch)
    root = tmp_path / "agents-sidecar"
    agents_dir = root / "agents"
    _mkagent(agents_dir, "bbugyi.athena.chop.no_such_chop.0_000000.1")

    assert project_chop_agent_rows(_inputs(root)) == ()


def test_no_agents_root_is_a_no_op() -> None:
    assert project_chop_agent_rows(_inputs(None)) == ()


def test_warm_run_reuses_cache_when_nothing_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_axe_config(monkeypatch)
    root = tmp_path / "agents-sidecar"
    agents_dir = root / "agents"
    _mkagent(agents_dir, "bbugyi.athena.chop.refresh_docs.sase.0_123456.1")

    first = project_chop_agent_rows(_inputs(root))
    second = project_chop_agent_rows(_inputs(root))

    assert first == second


def test_a_new_agent_directory_is_picked_up_on_the_next_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_axe_config(monkeypatch)
    root = tmp_path / "agents-sidecar"
    agents_dir = root / "agents"
    _mkagent(agents_dir, "bbugyi.athena.chop.refresh_docs.sase.0_123456.1")
    first = project_chop_agent_rows(_inputs(root))
    assert len(first) == 1

    _mkagent(agents_dir, "bbugyi.athena.chop.refresh_docs.sase.9_999999.2")
    second = project_chop_agent_rows(_inputs(root))

    assert len(second) == 2
