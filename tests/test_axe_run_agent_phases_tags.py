"""Tests for runner prompt-tag persistence."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.agent_tags import load_agent_tags, save_agent_tags
from sase.ace.tui.models.agent import AgentType
from sase.axe.run_agent_phases import AgentInfo, extract_directives_and_write_meta
from sase.llm_provider.temporary_override import set_temporary_override


def test_extract_directives_persists_tag_with_atomic_helper(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace_dir = tmp_path / "workspace"
    artifacts_dir = tmp_path / "artifacts" / "20260506120000"
    workspace_dir.mkdir()
    artifacts_dir.mkdir(parents=True)
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)

    with (
        patch(
            "sase.llm_provider.temporary_override."
            "resolve_effective_default_provider_model",
            return_value=("codex", "gpt-5"),
        ),
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        patch("sase.agent.names.claim_agent_name"),
        patch("sase.ace.agent_tags.update_agent_tag") as update_agent_tag,
    ):
        info = extract_directives_and_write_meta(
            "%name:taggy\n%group:sase-26\nDo work",
            str(workspace_dir),
            str(artifacts_dir),
            cl_name="sample-cl",
        )

    assert info.tag == "sase-26"
    assert json.loads((artifacts_dir / "agent_meta.json").read_text())["tag"] == (
        "sase-26"
    )
    update_agent_tag.assert_called_once_with(
        (AgentType.WORKFLOW, "sample-cl", "20260506120000"),
        "sase-26",
    )


def _extract_with_agent_tags(
    tmp_path: Path,
    prompt: str,
    *,
    seed_tags: dict[tuple[AgentType, str, str | None], str],
    cl_name: str | None = "sample-cl",
    planned_name: str | None = None,
    raw_resolved_prompt: str | None = None,
    artifacts_suffix: str = "20260506121000",
) -> tuple[AgentInfo, dict[str, object], dict[tuple[AgentType, str, str | None], str]]:
    workspace_dir = tmp_path / "workspace"
    artifacts_dir = tmp_path / "artifacts" / artifacts_suffix
    tag_file = tmp_path / "agent_tags.json"
    workspace_dir.mkdir()
    artifacts_dir.mkdir(parents=True)

    env_patch = {}
    if planned_name is not None:
        env_patch["SASE_AGENT_PLANNED_NAME"] = planned_name

    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", tag_file):
        assert save_agent_tags(seed_tags)
        with (
            patch.dict("os.environ", env_patch, clear=False),
            patch(
                "sase.llm_provider.temporary_override."
                "resolve_effective_default_provider_model",
                return_value=("codex", "gpt-5"),
            ),
            patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
            patch("sase.agent.names.claim_agent_name"),
        ):
            info = extract_directives_and_write_meta(
                prompt,
                str(workspace_dir),
                str(artifacts_dir),
                cl_name=cl_name,
                raw_resolved_prompt=raw_resolved_prompt,
            )

        meta = json.loads((artifacts_dir / "agent_meta.json").read_text())
        tags = load_agent_tags()
    return info, meta, tags


def test_explicit_group_wins_over_matching_existing_group(tmp_path: Path) -> None:
    existing = (AgentType.RUNNING, "seed", "ts1")
    identity = (AgentType.WORKFLOW, "sample-cl", "20260506121000")

    info, meta, tags = _extract_with_agent_tags(
        tmp_path,
        "%name:foo.child\n%group:bar\nDo work",
        seed_tags={existing: "foo"},
    )

    assert info.tag == "bar"
    assert meta["tag"] == "bar"
    assert tags == {
        existing: "foo",
        identity: "bar",
    }


def test_named_agent_auto_persists_existing_group(tmp_path: Path) -> None:
    existing = (AgentType.RUNNING, "seed", "ts1")
    identity = (AgentType.WORKFLOW, "sample-cl", "20260506121000")

    info, meta, tags = _extract_with_agent_tags(
        tmp_path,
        "%name:foo.child\nDo work",
        seed_tags={existing: "foo"},
    )

    assert info.tag == "foo"
    assert meta["tag"] == "foo"
    assert tags == {
        existing: "foo",
        identity: "foo",
    }


def test_wait_derived_agent_name_auto_persists_existing_group(
    tmp_path: Path,
) -> None:
    existing = (AgentType.RUNNING, "seed", "ts1")
    identity = (AgentType.WORKFLOW, "sample-cl", "20260506121000")

    info, meta, tags = _extract_with_agent_tags(
        tmp_path,
        "%wait:foo\nDo work",
        seed_tags={existing: "foo"},
    )

    assert info.name == "foo.w0"
    assert info.tag == "foo"
    assert meta["tag"] == "foo"
    assert tags == {
        existing: "foo",
        identity: "foo",
    }


def test_fork_derived_agent_name_auto_persists_existing_group(
    tmp_path: Path,
) -> None:
    existing = (AgentType.RUNNING, "seed", "ts1")
    identity = (AgentType.WORKFLOW, "sample-cl", "20260506121000")

    info, meta, tags = _extract_with_agent_tags(
        tmp_path,
        "expanded prompt",
        seed_tags={existing: "foo"},
        raw_resolved_prompt="#fork:foo\nDo work",
    )

    assert info.name == "foo.f0"
    assert info.tag == "foo"
    assert meta["tag"] == "foo"
    assert tags == {
        existing: "foo",
        identity: "foo",
    }


def test_planned_template_name_auto_uses_final_longest_group(
    tmp_path: Path,
) -> None:
    parent = (AgentType.RUNNING, "seed-parent", "ts1")
    child = (AgentType.RUNNING, "seed-child", "ts2")
    identity = (AgentType.WORKFLOW, "sample-cl", "20260506121000")

    info, meta, tags = _extract_with_agent_tags(
        tmp_path,
        "%name:sase-42.3.@\nDo work",
        seed_tags={
            parent: "sase-42",
            child: "sase-42.3",
        },
        planned_name="sase-42.3.1",
    )

    assert info.name == "sase-42.3.1"
    assert info.tag == "sase-42.3"
    assert meta["tag"] == "sase-42.3"
    assert tags == {
        parent: "sase-42",
        child: "sase-42.3",
        identity: "sase-42.3",
    }


def test_no_existing_group_skips_tag_metadata_and_store_write(
    tmp_path: Path,
) -> None:
    _info, meta, tags = _extract_with_agent_tags(
        tmp_path,
        "%name:foo.child\nDo work",
        seed_tags={},
    )

    assert "tag" not in meta
    assert tags == {}


def _mock_provider_config(
    monkeypatch: pytest.MonkeyPatch, cfg: dict[str, object]
) -> None:
    monkeypatch.setattr("sase.llm_provider.config.get_llm_provider_config", lambda: cfg)
    monkeypatch.setattr(
        "sase.llm_provider.registry.get_llm_provider_config", lambda: cfg
    )


def _extract_phase_worker_model_meta(tmp_path: Path) -> dict[str, object]:
    workspace_dir = tmp_path / "workspace"
    artifacts_dir = tmp_path / "artifacts"
    workspace_dir.mkdir()
    artifacts_dir.mkdir()

    with (
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        patch("sase.agent.names.claim_agent_name"),
    ):
        extract_directives_and_write_meta(
            "%name:phase-worker\n%model:@phase_worker\nDo work",
            str(workspace_dir),
            str(artifacts_dir),
        )

    return json.loads((artifacts_dir / "agent_meta.json").read_text())


def test_phase_worker_directive_metadata_resolves_default_lane(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``%model:@phase_worker`` phase records the resolved default-lane model.

    The worker lane was retired in epic sase-5d phase 4; ``@phase_worker`` now
    falls through to ``@default``, so the recorded metadata is the configured
    default provider's large-tier model. As an explicit ``@`` alias reference it
    resolves to the configured default and is not swayed by a primary override.
    """
    _mock_provider_config(monkeypatch, {"provider": "claude"})
    set_temporary_override("codex/o3", 3600.0, source="test")

    meta = _extract_phase_worker_model_meta(tmp_path)

    assert (meta["llm_provider"], meta["model"]) == ("claude", "opus")
