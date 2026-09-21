"""Tests for refreshing stale runner code after dependency waits."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.run_agent_runner_refresh import (
    RUNNER_CODE_REFRESHED_ENV,
    _source_code_identity,
    refresh_runner_code_after_wait,
)
from sase.version._models import GitProbeResult, GitVersionMetadata


def _git_result(commit: str) -> GitProbeResult:
    return GitProbeResult(
        GitVersionMetadata(
            root="/repo",
            commit=commit,
            short_commit=commit[:9],
            tag=None,
            distance=None,
            dirty=False,
        )
    )


def test_source_code_identity_tracks_head_changes() -> None:
    checkout = Path("/repo")
    old = "a" * 40
    new = "b" * 40
    with patch(
        "sase.axe.run_agent_runner_refresh.probe_git_metadata_at_ref",
        side_effect=[_git_result(old), _git_result(old), _git_result(new)],
    ):
        assert _source_code_identity(checkout) == old
        assert _source_code_identity(checkout) == old
        assert _source_code_identity(checkout) == new


def test_source_code_identity_is_inert_without_git_metadata() -> None:
    with patch(
        "sase.axe.run_agent_runner_refresh.probe_git_metadata_at_ref",
        return_value=GitProbeResult(None, "not a git checkout"),
    ):
        assert _source_code_identity(Path("/wheel")) is None
    assert _source_code_identity(None) is None


def test_changed_identity_reexecs_original_argv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    old = "a" * 40
    new = "b" * 40
    prompt_file = tmp_path / "submitted-prompt.md"
    submitted_xprompt = "%i(fix)\nKeep this exact prompt\n"

    def assert_exec_handoff(*_args: object) -> None:
        assert prompt_file.read_text(encoding="utf-8") == submitted_xprompt
        assert os.environ[RUNNER_CODE_REFRESHED_ENV] == "1"

    with (
        patch(
            "sase.axe.run_agent_runner_refresh.runner_code_identity",
            return_value=new,
        ),
        patch(
            "sase.axe.run_agent_runner_refresh.os.execv",
            side_effect=assert_exec_handoff,
        ) as execv,
        patch.object(sys, "executable", "/venv/bin/python"),
        patch.object(sys, "argv", ["runner.py", "--workspace-num", "7"]),
    ):
        refresh_runner_code_after_wait(
            old,
            blocking_wait_occurred=True,
            killed=False,
            prompt_file=str(prompt_file),
            submitted_xprompt=submitted_xprompt,
        )

    execv.assert_called_once_with(
        "/venv/bin/python",
        ["/venv/bin/python", "runner.py", "--workspace-num", "7"],
    )
    assert os.environ[RUNNER_CODE_REFRESHED_ENV] == "1"


def test_refresh_handoff_preserves_current_agent_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    monkeypatch.setenv("SASE_AGENT_PLANNED_NAME", "stale-parent")
    prompt_file = tmp_path / "submitted-prompt.md"

    def assert_exec_handoff(*_args: object) -> None:
        assert os.environ[RUNNER_CODE_REFRESHED_ENV] == "1"
        assert os.environ["SASE_AGENT_PLANNED_NAME"] == "builder.w0"

    with (
        patch(
            "sase.axe.run_agent_runner_refresh.runner_code_identity",
            return_value="b" * 40,
        ),
        patch(
            "sase.axe.run_agent_runner_refresh._validated_continuation_planned_name",
            return_value="builder.w0",
        ),
        patch(
            "sase.axe.run_agent_runner_refresh.os.execv",
            side_effect=assert_exec_handoff,
        ),
    ):
        refresh_runner_code_after_wait(
            "a" * 40,
            blocking_wait_occurred=True,
            killed=False,
            prompt_file=str(prompt_file),
            submitted_xprompt="%wait:builder\nDo work",
            agent_name="builder.w0",
            artifacts_dir=str(tmp_path / "artifacts"),
        )

    assert os.environ["SASE_AGENT_PLANNED_NAME"] == "builder.w0"


def test_refresh_handoff_drops_stale_planned_name_without_current_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    monkeypatch.setenv("SASE_AGENT_PLANNED_NAME", "stale-parent")
    prompt_file = tmp_path / "submitted-prompt.md"

    def assert_exec_handoff(*_args: object) -> None:
        assert os.environ[RUNNER_CODE_REFRESHED_ENV] == "1"
        assert "SASE_AGENT_PLANNED_NAME" not in os.environ

    with (
        patch(
            "sase.axe.run_agent_runner_refresh.runner_code_identity",
            return_value="b" * 40,
        ),
        patch(
            "sase.axe.run_agent_runner_refresh._validated_continuation_planned_name",
            return_value=None,
        ),
        patch(
            "sase.axe.run_agent_runner_refresh.os.execv",
            side_effect=assert_exec_handoff,
        ),
    ):
        refresh_runner_code_after_wait(
            "a" * 40,
            blocking_wait_occurred=True,
            killed=False,
            prompt_file=str(prompt_file),
            submitted_xprompt="%wait:builder\nDo work",
            agent_name="foreign.w0",
            artifacts_dir=str(tmp_path / "artifacts"),
        )

    assert "SASE_AGENT_PLANNED_NAME" not in os.environ


def test_exec_failure_restores_prior_planned_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    monkeypatch.setenv("SASE_AGENT_PLANNED_NAME", "stale-parent")
    prompt_file = tmp_path / "prompt.md"
    with (
        patch(
            "sase.axe.run_agent_runner_refresh.runner_code_identity",
            return_value="b" * 40,
        ),
        patch(
            "sase.axe.run_agent_runner_refresh._validated_continuation_planned_name",
            return_value="builder.w0",
        ),
        patch(
            "sase.axe.run_agent_runner_refresh.os.execv",
            side_effect=OSError("exec failed"),
        ),
    ):
        refresh_runner_code_after_wait(
            "a" * 40,
            blocking_wait_occurred=True,
            killed=False,
            prompt_file=str(prompt_file),
            submitted_xprompt="prompt",
            agent_name="builder.w0",
            artifacts_dir=str(tmp_path / "artifacts"),
        )

    assert RUNNER_CODE_REFRESHED_ENV not in os.environ
    assert os.environ["SASE_AGENT_PLANNED_NAME"] == "stale-parent"
    assert not prompt_file.exists()
    assert "continuing: exec failed" in capsys.readouterr().err


def test_prompt_rewrite_failure_skips_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    prompt_file = tmp_path / "missing" / "prompt.md"
    with (
        patch(
            "sase.axe.run_agent_runner_refresh.runner_code_identity",
            return_value="b" * 40,
        ),
        patch("sase.axe.run_agent_runner_refresh.os.execv") as execv,
    ):
        refresh_runner_code_after_wait(
            "a" * 40,
            blocking_wait_occurred=True,
            killed=False,
            prompt_file=str(prompt_file),
            submitted_xprompt="prompt",
        )

    execv.assert_not_called()
    assert RUNNER_CODE_REFRESHED_ENV not in os.environ
    assert "Skipping sase runner code refresh" in capsys.readouterr().err


def test_exec_failure_continues_without_refresh_guard_or_prompt_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    prompt_file = tmp_path / "prompt.md"
    with (
        patch(
            "sase.axe.run_agent_runner_refresh.runner_code_identity",
            return_value="b" * 40,
        ),
        patch(
            "sase.axe.run_agent_runner_refresh.os.execv",
            side_effect=OSError("exec failed"),
        ),
    ):
        refresh_runner_code_after_wait(
            "a" * 40,
            blocking_wait_occurred=True,
            killed=False,
            prompt_file=str(prompt_file),
            submitted_xprompt="prompt",
        )

    assert RUNNER_CODE_REFRESHED_ENV not in os.environ
    assert not prompt_file.exists()
    assert "continuing: exec failed" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("startup_identity", "current_identity", "blocked", "killed"),
    [
        ("a" * 40, "a" * 40, True, False),
        ("a" * 40, "b" * 40, False, False),
        ("a" * 40, "b" * 40, True, True),
        (None, "b" * 40, True, False),
    ],
    ids=("unchanged", "no-blocking-wait", "killed", "unknown-startup"),
)
def test_refresh_is_inert_without_all_preconditions(
    monkeypatch: pytest.MonkeyPatch,
    startup_identity: str | None,
    current_identity: str,
    blocked: bool,
    killed: bool,
) -> None:
    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    with (
        patch(
            "sase.axe.run_agent_runner_refresh.runner_code_identity",
            return_value=current_identity,
        ),
        patch("sase.axe.run_agent_runner_refresh.os.execv") as execv,
    ):
        refresh_runner_code_after_wait(
            startup_identity,
            blocking_wait_occurred=blocked,
            killed=killed,
            prompt_file="/tmp/prompt.md",
            submitted_xprompt="prompt",
        )

    execv.assert_not_called()
    assert RUNNER_CODE_REFRESHED_ENV not in os.environ


def test_refreshed_guard_prevents_loop_and_is_not_inherited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(RUNNER_CODE_REFRESHED_ENV, "1")
    with (
        patch(
            "sase.axe.run_agent_runner_refresh.runner_code_identity"
        ) as current_identity,
        patch("sase.axe.run_agent_runner_refresh.os.execv") as execv,
    ):
        refresh_runner_code_after_wait(
            "a" * 40,
            blocking_wait_occurred=True,
            killed=False,
            prompt_file="/tmp/prompt.md",
            submitted_xprompt="prompt",
        )

    current_identity.assert_not_called()
    execv.assert_not_called()
    assert RUNNER_CODE_REFRESHED_ENV not in os.environ


def test_refresh_rematerializes_local_xprompts_for_exec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.multi_prompt_xprompts import (
        LOCAL_XPROMPTS_ENV,
        deserialize_local_xprompts,
    )
    from sase.xprompt.models import XPrompt

    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    monkeypatch.delenv(LOCAL_XPROMPTS_ENV, raising=False)
    prompt_file = tmp_path / "prompt.md"
    xprompts = {"_x": XPrompt(name="_x", content="expanded body")}
    captured: dict[str, str] = {}

    def capture_exec(*_args: object) -> None:
        captured.update(os.environ)
        assert LOCAL_XPROMPTS_ENV in captured

    with (
        patch(
            "sase.axe.run_agent_runner_refresh.runner_code_identity",
            return_value="b" * 40,
        ),
        patch(
            "sase.axe.run_agent_runner_refresh.os.execv",
            side_effect=capture_exec,
        ),
    ):
        refresh_runner_code_after_wait(
            "a" * 40,
            blocking_wait_occurred=True,
            killed=False,
            prompt_file=str(prompt_file),
            submitted_xprompt="prompt",
            local_xprompts=xprompts,
        )

    path = captured[LOCAL_XPROMPTS_ENV]
    assert os.environ[LOCAL_XPROMPTS_ENV] == path
    round_tripped = deserialize_local_xprompts(path)
    assert set(round_tripped) == {"_x"}
    assert round_tripped["_x"].content == "expanded body"


def test_refresh_exec_failure_restores_local_xprompts_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.multi_prompt_xprompts import LOCAL_XPROMPTS_ENV
    from sase.xprompt.models import XPrompt

    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    monkeypatch.delenv(LOCAL_XPROMPTS_ENV, raising=False)
    prompt_file = tmp_path / "prompt.md"
    xprompts = {"_x": XPrompt(name="_x", content="body")}

    with (
        patch(
            "sase.axe.run_agent_runner_refresh.runner_code_identity",
            return_value="b" * 40,
        ),
        patch(
            "sase.axe.run_agent_runner_refresh.os.execv",
            side_effect=OSError("exec failed"),
        ),
    ):
        refresh_runner_code_after_wait(
            "a" * 40,
            blocking_wait_occurred=True,
            killed=False,
            prompt_file=str(prompt_file),
            submitted_xprompt="prompt",
            local_xprompts=xprompts,
        )

    assert LOCAL_XPROMPTS_ENV not in os.environ
    assert RUNNER_CODE_REFRESHED_ENV not in os.environ


def test_refresh_exec_failure_restores_prior_local_xprompts_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.multi_prompt_xprompts import LOCAL_XPROMPTS_ENV
    from sase.xprompt.models import XPrompt

    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    prior = tmp_path / "prior.json"
    prior.write_text("{}", encoding="utf-8")
    monkeypatch.setenv(LOCAL_XPROMPTS_ENV, str(prior))
    prompt_file = tmp_path / "prompt.md"
    xprompts = {"_x": XPrompt(name="_x", content="body")}
    created: list[str] = []
    real_serialize = None

    import sase.agent.multi_prompt_xprompts as xprompt_module

    real_serialize = xprompt_module.serialize_local_xprompts

    def tracking_serialize(payload: object) -> str:
        path = real_serialize(payload)  # type: ignore[arg-type]
        created.append(path)
        return path

    with (
        patch(
            "sase.axe.run_agent_runner_refresh.runner_code_identity",
            return_value="b" * 40,
        ),
        patch(
            "sase.agent.multi_prompt_xprompts.serialize_local_xprompts",
            side_effect=tracking_serialize,
        ),
        patch(
            "sase.axe.run_agent_runner_refresh.os.execv",
            side_effect=OSError("exec failed"),
        ),
    ):
        refresh_runner_code_after_wait(
            "a" * 40,
            blocking_wait_occurred=True,
            killed=False,
            prompt_file=str(prompt_file),
            submitted_xprompt="prompt",
            local_xprompts=xprompts,
        )

    assert os.environ[LOCAL_XPROMPTS_ENV] == str(prior)
    assert created and not os.path.exists(created[0])


@pytest.mark.parametrize("local_xprompts", [None, {}])
def test_refresh_leaves_local_xprompts_env_untouched_when_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    local_xprompts: object,
) -> None:
    from sase.agent.multi_prompt_xprompts import LOCAL_XPROMPTS_ENV

    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    monkeypatch.delenv(LOCAL_XPROMPTS_ENV, raising=False)
    prompt_file = tmp_path / "prompt.md"

    with (
        patch(
            "sase.axe.run_agent_runner_refresh.runner_code_identity",
            return_value="b" * 40,
        ),
        patch(
            "sase.axe.run_agent_runner_refresh.os.execv",
            side_effect=lambda *_args: None,
        ),
    ):
        refresh_runner_code_after_wait(
            "a" * 40,
            blocking_wait_occurred=True,
            killed=False,
            prompt_file=str(prompt_file),
            submitted_xprompt="prompt",
            local_xprompts=local_xprompts,  # type: ignore[arg-type]
        )

    assert LOCAL_XPROMPTS_ENV not in os.environ


def test_refresh_serialization_failure_skips_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.agent.multi_prompt_xprompts import LOCAL_XPROMPTS_ENV
    from sase.xprompt.models import XPrompt

    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    monkeypatch.delenv(LOCAL_XPROMPTS_ENV, raising=False)
    prompt_file = tmp_path / "prompt.md"

    with (
        patch(
            "sase.axe.run_agent_runner_refresh.runner_code_identity",
            return_value="b" * 40,
        ),
        patch(
            "sase.agent.multi_prompt_xprompts.serialize_local_xprompts",
            side_effect=RuntimeError("cannot serialize"),
        ),
        patch("sase.axe.run_agent_runner_refresh.os.execv") as execv,
    ):
        refresh_runner_code_after_wait(
            "a" * 40,
            blocking_wait_occurred=True,
            killed=False,
            prompt_file=str(prompt_file),
            submitted_xprompt="prompt",
            local_xprompts={"_x": XPrompt(name="_x", content="body")},
        )

    execv.assert_not_called()
    assert RUNNER_CODE_REFRESHED_ENV not in os.environ
    assert LOCAL_XPROMPTS_ENV not in os.environ
    assert "local xprompts could not be re-materialized" in capsys.readouterr().err


def test_refresh_local_xprompts_boundary_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First extract -> refresh -> second extract keeps local xprompts."""
    import json

    from sase.agent.multi_prompt_launcher import _serialize_local_xprompts
    from sase.axe.run_agent_directives import extract_directives_and_write_meta
    from sase.agent.multi_prompt_xprompts import LOCAL_XPROMPTS_ENV
    from sase.xprompt.models import XPrompt
    from tests._agent_names_extract_fixtures import mock_provider

    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    workspace = tmp_path / "workspace"
    artifacts = tmp_path / "artifacts"
    workspace.mkdir()
    artifacts.mkdir()
    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    monkeypatch.delenv(LOCAL_XPROMPTS_ENV, raising=False)

    first_path = _serialize_local_xprompts(
        {"_x": XPrompt(name="_x", content="expanded body")}
    )
    monkeypatch.setenv(LOCAL_XPROMPTS_ENV, first_path)

    def run_extract(prompt: str) -> object:
        with (
            patch(
                "sase.llm_provider.registry.get_default_provider_name",
                return_value="test",
            ),
            patch(
                "sase.llm_provider.registry.get_provider",
                return_value=mock_provider(),
            ),
            patch(
                "sase.llm_provider.registry.resolve_model_provider",
                return_value=("test", "test-model"),
            ),
            patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        ):
            os.environ.pop("SASE_AGENT_FAMILY_ATTACH", None)
            return extract_directives_and_write_meta(
                prompt,
                str(workspace),
                str(artifacts),
            )

    first = run_extract("#_x\nplease")
    assert set(first.local_xprompts) == {"_x"}
    assert LOCAL_XPROMPTS_ENV not in os.environ

    captured: dict[str, str] = {}

    def capture_exec(*_args: object) -> None:
        captured.update(os.environ)

    prompt_file = tmp_path / "prompt.md"
    with (
        patch(
            "sase.axe.run_agent_runner_refresh.runner_code_identity",
            return_value="b" * 40,
        ),
        patch(
            "sase.axe.run_agent_runner_refresh.os.execv",
            side_effect=capture_exec,
        ),
    ):
        refresh_runner_code_after_wait(
            "a" * 40,
            blocking_wait_occurred=True,
            killed=False,
            prompt_file=str(prompt_file),
            submitted_xprompt="#_x\nplease",
            local_xprompts=first.local_xprompts,
        )

    assert LOCAL_XPROMPTS_ENV in captured
    with patch.dict(os.environ, captured, clear=False):
        second = run_extract("#_x\nplease")

    assert set(second.local_xprompts) == {"_x"}
    assert second.local_xprompts["_x"].content == "expanded body"
    assert json.loads((artifacts / "agent_meta.json").read_text(encoding="utf-8"))
