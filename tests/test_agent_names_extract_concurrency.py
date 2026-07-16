"""Concurrency and launch-state tests for agent directive extraction."""

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import time
from unittest.mock import patch

from sase.agent.names import NameCollisionError
from tests._agent_names_extract_fixtures import mock_provider


def test_concurrent_auto_extract_assigns_unique_names(tmp_path: Path) -> None:
    from sase.agent.names import get_next_auto_name as real_get_next_auto_name
    from sase.axe.run_agent_phases import extract_directives_and_write_meta

    def slow_get_next_auto_name() -> str:
        name = real_get_next_auto_name()
        time.sleep(0.05)
        return name

    def run(index: int) -> str:
        workspace = tmp_path / f"workspace{index}"
        artifacts = (
            tmp_path
            / ".sase"
            / "projects"
            / "proj"
            / "artifacts"
            / "ace-run"
            / f"run{index}"
        )
        workspace.mkdir(parents=True)
        artifacts.mkdir(parents=True)
        info = extract_directives_and_write_meta(
            "do stuff",
            str(workspace),
            str(artifacts),
            cl_name="feature-branch",
        )
        return str(info.name)

    for key in (
        "SASE_AGENT_AUTO_DISMISS",
        "SASE_AGENT_PLANNED_NAME",
        "SASE_REPEAT_NAME",
    ):
        os.environ.pop(key, None)

    with (
        patch.object(Path, "home", return_value=tmp_path),
        patch(
            "sase.agent.names.get_next_auto_name",
            side_effect=slow_get_next_auto_name,
        ),
        patch("sase.xprompt.process_xprompt_references", side_effect=lambda p, **kw: p),
        patch(
            "sase.llm_provider.registry.get_default_provider_name",
            return_value="test",
        ),
        patch("sase.llm_provider.registry.get_provider", return_value=mock_provider()),
        patch(
            "sase.llm_provider.registry.resolve_model_provider",
            return_value=("test", "test-model"),
        ),
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        names = list(pool.map(run, range(2)))

    assert sorted(names) == ["0", "1"]


def test_concurrent_explicit_extract_rejects_collision(tmp_path: Path) -> None:
    from sase.axe.run_agent_phases import extract_directives_and_write_meta

    def run(index: int) -> tuple[str, str]:
        workspace = tmp_path / f"workspace{index}"
        artifacts = (
            tmp_path
            / ".sase"
            / "projects"
            / "proj"
            / "artifacts"
            / "ace-run"
            / f"run{index}"
        )
        workspace.mkdir(parents=True)
        artifacts.mkdir(parents=True)
        try:
            info = extract_directives_and_write_meta(
                "%name:dupe do stuff",
                str(workspace),
                str(artifacts),
                cl_name="feature-branch",
            )
        except NameCollisionError as exc:
            return "error", str(exc)
        return "ok", str(info.name)

    for key in (
        "SASE_AGENT_AUTO_DISMISS",
        "SASE_AGENT_PLANNED_NAME",
        "SASE_REPEAT_NAME",
    ):
        os.environ.pop(key, None)

    with (
        patch.object(Path, "home", return_value=tmp_path),
        patch("sase.xprompt.process_xprompt_references", side_effect=lambda p, **kw: p),
        patch(
            "sase.llm_provider.registry.get_default_provider_name",
            return_value="test",
        ),
        patch("sase.llm_provider.registry.get_provider", return_value=mock_provider()),
        patch(
            "sase.llm_provider.registry.resolve_model_provider",
            return_value=("test", "test-model"),
        ),
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        results = list(pool.map(run, range(2)))

    statuses = [status for status, _ in results]
    assert statuses.count("ok") == 1
    assert statuses.count("error") == 1
    assert any("dupe1" in detail for status, detail in results if status == "error")


def test_generated_name_marker_env_is_consumed(tmp_path: Path) -> None:
    """The generated-name marker applies to this launch only.

    If it lingers in the environment, nested launches spawned by this agent
    inherit it and treat their own explicit %name directives as generated,
    silently skipping name collision checks.
    """
    from sase.axe.run_agent_phases import extract_directives_and_write_meta

    workspace = str(tmp_path / "workspace")
    artifacts = str(tmp_path / "artifacts")
    os.makedirs(workspace, exist_ok=True)
    os.makedirs(artifacts, exist_ok=True)

    with (
        patch.object(Path, "home", return_value=tmp_path),
        patch("sase.agent.names.claim_agent_name"),
        patch.dict(os.environ, {"SASE_AGENT_GENERATED_NAME": "1"}, clear=False),
        patch("sase.xprompt.process_xprompt_references", side_effect=lambda p, **kw: p),
        patch(
            "sase.llm_provider.registry.get_default_provider_name",
            return_value="test",
        ),
        patch("sase.llm_provider.registry.get_provider", return_value=mock_provider()),
        patch(
            "sase.llm_provider.registry.resolve_model_provider",
            return_value=("test", "test-model"),
        ),
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
    ):
        extract_directives_and_write_meta(
            "%name:genx\nDo work",
            workspace,
            artifacts,
            cl_name="test_cl",
            raw_resolved_prompt="%name:genx\nDo work",
        )

        assert "SASE_AGENT_GENERATED_NAME" not in os.environ
