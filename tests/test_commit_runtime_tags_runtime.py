"""Runtime identity and automatic commit tag behavior."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.workflows.commit.runtime_tags import (
    PRODUCED_RUNTIME_COMMIT_TAG_KEYS,
    RUNTIME_COMMIT_TAG_KEYS,
    RUN_OWNED_COMMIT_TAG_KEYS,
    STALE_RUNTIME_COMMIT_TAG_KEYS,
    _resolve_runtime_commit_tags,
    apply_auto_commit_tags_with_runtime,
    apply_runtime_commit_tags,
    apply_tracked_commit_tags,
    parse_trailing_commit_tags,
    resolve_local_agent_name,
)
from _commit_runtime_tags_test_support import (
    clean_runtime_env as clean_runtime_env,
    owner_target,
)


def test_runtime_tags_use_sase_agent_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-alpha")
    assert _resolve_runtime_commit_tags() == {
        "AGENT": "alice.machine_a.agent-alpha",
    }


def test_produced_and_stale_runtime_tag_keys_are_deliberately_separate() -> None:
    assert PRODUCED_RUNTIME_COMMIT_TAG_KEYS == {"AGENT", "MODEL"}
    assert STALE_RUNTIME_COMMIT_TAG_KEYS == {"AGENT", "MACHINE", "MODEL"}
    assert RUN_OWNED_COMMIT_TAG_KEYS == {"AGENT", "MODEL", "TYPE", "BEAD"}
    assert RUNTIME_COMMIT_TAG_KEYS == STALE_RUNTIME_COMMIT_TAG_KEYS


def test_runtime_tags_stamp_the_producing_turn_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "agent_meta.json").write_text(
        json.dumps(
            {"name": "agent-current", "llm_provider": "claude", "model": "opus"}
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-current")
    monkeypatch.setenv("SASE_AGENT_LLM_PROVIDER", "runner-default")

    assert _resolve_runtime_commit_tags() == {
        "AGENT": "alice.machine_a.agent-current",
        "MODEL": "claude/opus",
    }


def test_runtime_tags_stamp_fallback_retry_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "agent_meta.json").write_text(
        json.dumps(
            {"name": "agent-current", "llm_provider": "claude", "model": "opus"}
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-current")
    monkeypatch.setenv("SASE_MODEL_OVERRIDE", "quick")
    with patch(
        "sase.llm_provider.registry.resolve_model_provider",
        return_value=("codex", "o3"),
    ) as resolve_model_provider:
        assert _resolve_runtime_commit_tags()["MODEL"] == "codex/o3"
    resolve_model_provider.assert_called_once_with("quick", consume=False)


def test_runtime_tags_prefer_configured_machine_and_qualify_legacy_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-alpha")
    monkeypatch.setattr(
        owner_target,
        lambda: AgentOwnerIdentity("alice", "athena"),
    )

    assert _resolve_runtime_commit_tags() == {
        "AGENT": "alice.athena.agent-alpha",
    }


def test_runtime_tags_do_not_double_qualify_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_NAME", "athena.agent-alpha")
    monkeypatch.setattr(
        owner_target,
        lambda: AgentOwnerIdentity("alice", "athena"),
    )

    assert _resolve_runtime_commit_tags()["AGENT"] == "alice.athena.agent-alpha"


def test_runtime_tags_fall_back_to_agent_meta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"name": "agent-meta"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))

    assert _resolve_runtime_commit_tags() == {
        "AGENT": "alice.machine_a.agent-meta",
    }


def test_commit_agent_name_prefers_current_run_metadata_for_agent_session_member(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"name": "ms--code", "workflow_name": "ms"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("SASE_AGENT_NAME", "ms")

    assert resolve_local_agent_name() == "ms--code"


def test_commit_agent_name_is_unchanged_for_non_agent_session_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"name": "solo"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("SASE_AGENT_NAME", "solo")

    assert resolve_local_agent_name() == "solo"


def test_runtime_tags_omit_agent_when_no_name_exists() -> None:
    assert _resolve_runtime_commit_tags() == {}


def test_runtime_tags_sanitize_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_AGENT_NAME", "  agent-alpha\n  ")
    monkeypatch.setattr(
        owner_target,
        lambda: AgentOwnerIdentity("alice", "machine_host"),
    )
    assert _resolve_runtime_commit_tags() == {
        "AGENT": "alice.machine_host.agent-alpha",
    }


def test_runtime_tags_require_complete_owner_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-alpha")
    monkeypatch.setattr(
        owner_target,
        lambda: (_ for _ in ()).throw(RuntimeError("run `sase config init`")),
    )

    with pytest.raises(RuntimeError, match="sase config init"):
        _resolve_runtime_commit_tags()


def test_auto_commit_tags_with_runtime_type_only_without_agent_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without an agent identity, only ``TYPE=`` is written (no AGENT/MACHINE)."""
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)

    assert (
        apply_auto_commit_tags_with_runtime("Fix bug", "sdd")
        == "Fix bug\n\nSASE_TYPE=sdd"
    )


def test_auto_commit_without_agent_removes_stale_machine() -> None:
    assert apply_auto_commit_tags_with_runtime(
        "Fix bug\n\nSASE_MACHINE=legacy-host\nSASE_MODEL=legacy/model",
        "sdd",
    ) == ("Fix bug\n\nSASE_TYPE=sdd")


def test_runtime_commit_tags_remove_inherited_model_without_agent() -> None:
    payload = {"message": "Fix bug\n\nSASE_MODEL=legacy/model"}

    apply_runtime_commit_tags(payload)

    assert payload["message"] == "Fix bug"


def test_auto_commit_tags_with_runtime_adds_agent_when_name_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``SASE_AGENT_NAME`` adds the runtime ``AGENT=`` provenance tag."""
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-alpha")
    monkeypatch.setattr(
        owner_target,
        lambda: AgentOwnerIdentity("alice", "machine_z"),
    )

    updated = apply_auto_commit_tags_with_runtime("Fix bug", "sdd")

    tags = parse_trailing_commit_tags(updated)
    assert tags["TYPE"] == "sdd"
    assert tags["AGENT"] == "alice.machine_z.agent-alpha"
    assert "MACHINE" not in tags


def test_auto_commit_tags_with_runtime_projects_agent_session_member_to_sase_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``SASE_AGENT_NAME`` is the concrete shell; ``SASE_AGENT=`` is the sase agent."""
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"name": "foo.bar--code", "workflow_name": "foo.bar"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("SASE_AGENT_NAME", "foo.bar")
    monkeypatch.setattr(
        owner_target,
        lambda: AgentOwnerIdentity("alice", "athena"),
    )
    monkeypatch.setattr(
        "sase.agents_sync.links.resolve_checkout_anchor",
        lambda path: SimpleNamespace(primary_root=path, project_name=None),
    )

    assert resolve_local_agent_name() == "foo.bar--code"
    assert apply_auto_commit_tags_with_runtime("Fix bug", "sdd") == (
        "Fix bug\n\nSASE_TYPE=sdd\nSASE_AGENT=alice.athena.foo.bar"
    )


def test_sase_agent_name_env_is_the_concrete_shell_and_footer_is_the_sase_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_NAME", "pc--code")
    monkeypatch.setattr(
        owner_target,
        lambda: AgentOwnerIdentity("alice", "athena"),
    )

    assert resolve_local_agent_name() == "pc--code"
    assert _resolve_runtime_commit_tags() == {"AGENT": "alice.athena.pc"}


def test_runtime_producer_removes_inherited_legacy_machine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-alpha")
    payload = {"message": "Fix bug\n\nSASE_AGENT=old\nSASE_MACHINE=legacy-host"}

    apply_runtime_commit_tags(payload)

    assert parse_trailing_commit_tags(payload["message"]) == {
        "AGENT": "alice.machine_a.agent-alpha"
    }
    assert "MACHINE=" not in payload["message"]


def test_apply_tracked_commit_tags_adds_type_stitch() -> None:
    payload = {"message": "fix: bug"}

    apply_tracked_commit_tags(payload)

    assert payload["message"] == "fix: bug\n\nSASE_TYPE=stitch"


def test_apply_tracked_commit_tags_keeps_bead_and_plan_with_type_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-a")
    payload = {
        "message": (
            "fix: bug\n\nSASE_BEAD=[sase-ai.2][1]\nSASE_PLAN=[202608/plan.md][2]"
            "\n\n[1]: https://example.test/bead\n[2]: https://example.test/plan"
        )
    }

    apply_tracked_commit_tags(payload)

    tags = parse_trailing_commit_tags(payload["message"])
    assert tags["TYPE"] == "stitch"
    assert tags["AGENT"] == "alice.machine_a.agent-a"
    assert tags["BEAD"] == "sase-ai.2"
    assert tags["PLAN"] == "202608/plan.md"

    # TYPE (and AGENT) render first in the UI per _KEY_PRIORITY, independent
    # of raw footer append order.
    from sase.vcs_log._tag_style import _tag_chips

    ordered_keys = [chip.key for chip in _tag_chips(tuple(tags.items()))]
    assert ordered_keys.index("TYPE") < ordered_keys.index("BEAD")
    assert ordered_keys.index("TYPE") < ordered_keys.index("PLAN")


def test_apply_tracked_commit_tags_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-a")
    payload = {"message": "fix: bug"}

    apply_tracked_commit_tags(payload)
    once = payload["message"]
    apply_tracked_commit_tags(payload)

    assert payload["message"] == once
