"""Tests for refreshing stale runner code after dependency waits."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from sase.axe.run_agent_runner_state import RunnerRunState

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
    submitted_prompt = "%i(fix)\nKeep this exact prompt\n"

    def assert_exec_handoff(*_args: object) -> None:
        assert prompt_file.read_text(encoding="utf-8") == submitted_prompt
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
            submitted_prompt=submitted_prompt,
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
            submitted_prompt="%wait:builder\nDo work",
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
            submitted_prompt="%wait:builder\nDo work",
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
            submitted_prompt="prompt",
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
            submitted_prompt="prompt",
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
            submitted_prompt="prompt",
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
            submitted_prompt="prompt",
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
            submitted_prompt="prompt",
        )

    current_identity.assert_not_called()
    execv.assert_not_called()
    assert RUNNER_CODE_REFRESHED_ENV not in os.environ


def test_refresh_rematerializes_local_macros_for_exec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.multi_prompt_macros import (
        LOCAL_MACROS_ENV,
        deserialize_local_macros,
    )
    from sase.macro.models import Macro

    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    monkeypatch.delenv(LOCAL_MACROS_ENV, raising=False)
    prompt_file = tmp_path / "prompt.md"
    macros = {"_x": Macro(name="_x", content="expanded body")}
    captured: dict[str, str] = {}

    def capture_exec(*_args: object) -> None:
        captured.update(os.environ)
        assert LOCAL_MACROS_ENV in captured

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
            submitted_prompt="prompt",
            local_macros=macros,
        )

    path = captured[LOCAL_MACROS_ENV]
    assert os.environ[LOCAL_MACROS_ENV] == path
    round_tripped = deserialize_local_macros(path)
    assert set(round_tripped) == {"_x"}
    assert round_tripped["_x"].content == "expanded body"


def test_refresh_exec_failure_restores_local_macros_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.multi_prompt_macros import LOCAL_MACROS_ENV
    from sase.macro.models import Macro

    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    monkeypatch.delenv(LOCAL_MACROS_ENV, raising=False)
    prompt_file = tmp_path / "prompt.md"
    macros = {"_x": Macro(name="_x", content="body")}

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
            submitted_prompt="prompt",
            local_macros=macros,
        )

    assert LOCAL_MACROS_ENV not in os.environ
    assert RUNNER_CODE_REFRESHED_ENV not in os.environ


def test_refresh_exec_failure_restores_prior_local_macros_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.multi_prompt_macros import LOCAL_MACROS_ENV
    from sase.macro.models import Macro

    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    prior = tmp_path / "prior.json"
    prior.write_text("{}", encoding="utf-8")
    monkeypatch.setenv(LOCAL_MACROS_ENV, str(prior))
    prompt_file = tmp_path / "prompt.md"
    macros = {"_x": Macro(name="_x", content="body")}
    created: list[str] = []
    real_serialize = None

    import sase.agent.multi_prompt_macros as macro_module

    real_serialize = macro_module.serialize_local_macros

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
            "sase.axe.run_agent_runner_refresh.serialize_local_macros",
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
            submitted_prompt="prompt",
            local_macros=macros,
        )

    assert os.environ[LOCAL_MACROS_ENV] == str(prior)
    assert created and not os.path.exists(created[0])


@pytest.mark.parametrize("local_macros", [None, {}])
def test_refresh_leaves_local_macros_env_untouched_when_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    local_macros: object,
) -> None:
    from sase.agent.multi_prompt_macros import LOCAL_MACROS_ENV

    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    monkeypatch.delenv(LOCAL_MACROS_ENV, raising=False)
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
            submitted_prompt="prompt",
            local_macros=local_macros,  # type: ignore[arg-type]
        )

    assert LOCAL_MACROS_ENV not in os.environ


def test_refresh_serialization_failure_skips_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.agent.multi_prompt_macros import LOCAL_MACROS_ENV
    from sase.macro.models import Macro

    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    monkeypatch.delenv(LOCAL_MACROS_ENV, raising=False)
    prompt_file = tmp_path / "prompt.md"

    with (
        patch(
            "sase.axe.run_agent_runner_refresh.runner_code_identity",
            return_value="b" * 40,
        ),
        patch(
            "sase.axe.run_agent_runner_refresh.serialize_local_macros",
            side_effect=RuntimeError("cannot serialize"),
        ),
        patch("sase.axe.run_agent_runner_refresh.os.execv") as execv,
    ):
        refresh_runner_code_after_wait(
            "a" * 40,
            blocking_wait_occurred=True,
            killed=False,
            prompt_file=str(prompt_file),
            submitted_prompt="prompt",
            local_macros={"_x": Macro(name="_x", content="body")},
        )

    execv.assert_not_called()
    assert RUNNER_CODE_REFRESHED_ENV not in os.environ
    assert LOCAL_MACROS_ENV not in os.environ
    assert "local macros could not be re-materialized" in capsys.readouterr().err


def test_refresh_path_imports_no_new_sase_modules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Import firewall: the identity check to execv span imports no new code.

    A torn post-update tree cannot satisfy fresh imports, which is exactly
    how the 2026-10-09 ``auto_launch_prefix`` incident died. Any
    ``sase.*`` import after the identity check trips the firewall, so this
    reaches ``execv`` only when every refresh-path helper (including the
    lazily-imported leaves they touch) was already imported at boot.
    """
    from sase.agent.multi_prompt_macros import LOCAL_MACROS_ENV
    from sase.macro.models import Macro

    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    monkeypatch.delenv(LOCAL_MACROS_ENV, raising=False)
    prompt_file = tmp_path / "prompt.md"
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    submitted_prompt = "%wait:builder\nDo work"
    macros = {"_x": Macro(name="_x", content="expanded body")}
    attempted: list[str] = []

    class _ImportFirewall:
        def find_spec(
            self,
            fullname: str,
            path: object = None,
            target: object = None,
        ) -> object:
            if fullname == "sase" or fullname.startswith("sase."):
                attempted.append(fullname)
                raise ImportError(f"import-firewall: {fullname} imported late")
            return None

    firewall = _ImportFirewall()
    captured: dict[str, str] = {}

    def capture_exec(*_args: object) -> None:
        captured.update(os.environ)

    sys.meta_path.insert(0, firewall)
    try:
        with (
            patch(
                "sase.axe.run_agent_runner_refresh.runner_code_identity",
                return_value="b" * 40,
            ),
            patch(
                "sase.agent.names.planned_registered_name_belongs_to_artifact",
                return_value=True,
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
                submitted_prompt=submitted_prompt,
                agent_name="builder.w0",
                artifacts_dir=str(artifacts_dir),
                local_macros=macros,
            )
    finally:
        sys.meta_path.remove(firewall)

    assert attempted == []
    assert prompt_file.read_text(encoding="utf-8") == submitted_prompt
    assert captured[RUNNER_CODE_REFRESHED_ENV] == "1"
    assert captured["SASE_AGENT_PLANNED_NAME"] == "builder.w0"
    assert LOCAL_MACROS_ENV in captured


def _refreshed_bootstrap_state(tmp_path: Path, prompt_text: str) -> RunnerRunState:
    """Build a refreshed-pass state whose prompt file holds *prompt_text*."""
    from sase.axe.run_agent_runner_state import RunnerRunState

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text(prompt_text, encoding="utf-8")
    return RunnerRunState(
        cl_name="refresh-reconcile",
        project_file="/tmp/projects/sase/sase.sase",
        prompt_file=str(prompt_file),
        output_path=str(tmp_path / "output.log"),
        workflow_name="ace(run)-260701_010202",
        timestamp="260701_010202",
        update_target="",
        is_home_mode=False,
        workspace_dir=str(tmp_path / "workspace"),
        workspace_num=7,
        project_name="sase",
        artifacts_timestamp="20260701_010202",
        artifacts_dir=str(artifacts_dir),
    )


@pytest.mark.parametrize(
    ("live_meta", "stale_prompt", "expected_head"),
    [
        ({"name": "agent-x"}, "%auto\nDo the thing", None),
        ({"name": "agent-x"}, "%auto:plan\nDo the thing", None),
        ({"autonomy": {"selection": ""}}, "Do the thing", "%auto"),
        (
            {"autonomy": {"selection": "plan"}},
            "%auto\nDo the thing",
            "%auto:plan",
        ),
    ],
    ids=("toggle-off", "toggle-off-plan-spelling", "toggle-on", "auto-plan"),
)
def test_refreshed_pass_reconcile_keeps_wait_time_auto_toggle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    live_meta: dict[str, object],
    stale_prompt: str,
    expected_head: str | None,
) -> None:
    """An ``A`` toggle made during the wait survives the re-exec.

    The pre-exec path persists the prompt verbatim (it may not import), so
    the refreshed process must apply the live ``%auto`` reconcile before
    directive extraction; otherwise a toggle-off is undone and a toggle-on
    is lost.
    """
    import json

    from sase.axe.run_agent_runner_bootstrap import _load_submitted_prompt

    monkeypatch.setenv(RUNNER_CODE_REFRESHED_ENV, "1")
    state = _refreshed_bootstrap_state(tmp_path, stale_prompt)
    (Path(state.artifacts_dir) / "agent_meta.json").write_text(
        json.dumps(live_meta), encoding="utf-8"
    )

    _load_submitted_prompt(state)

    if expected_head is None:
        assert "%auto" not in state.prompt
    else:
        assert state.prompt.split("\n")[0].startswith(expected_head)
    assert "Do the thing" in state.prompt
    assert state.submitted_prompt == state.prompt


def test_non_refreshed_pass_leaves_prompt_unreconciled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reconcile hook is gated on the refresh marker."""
    from sase.axe.run_agent_runner_bootstrap import _load_submitted_prompt

    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    stale_prompt = "%auto\nDo the thing"
    state = _refreshed_bootstrap_state(tmp_path, stale_prompt)

    _load_submitted_prompt(state)

    assert state.prompt == stale_prompt


def test_refresh_local_macros_boundary_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First extract -> refresh -> second extract keeps local macros."""
    import json

    from sase.agent.multi_prompt_launcher import _serialize_local_macros
    from sase.axe.run_agent_directives import extract_directives_and_write_meta
    from sase.agent.multi_prompt_macros import LOCAL_MACROS_ENV
    from sase.macro.models import Macro
    from tests._agent_names_extract_fixtures import mock_provider

    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    workspace = tmp_path / "workspace"
    artifacts = tmp_path / "artifacts"
    workspace.mkdir()
    artifacts.mkdir()
    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    monkeypatch.delenv(LOCAL_MACROS_ENV, raising=False)

    first_path = _serialize_local_macros(
        {"_x": Macro(name="_x", content="expanded body")}
    )
    monkeypatch.setenv(LOCAL_MACROS_ENV, first_path)

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
            os.environ.pop("SASE_AGENT_SESSION_ATTACH", None)
            return extract_directives_and_write_meta(
                prompt,
                str(workspace),
                str(artifacts),
            )

    first = run_extract("#_x\nplease")
    assert set(first.local_macros) == {"_x"}
    assert LOCAL_MACROS_ENV not in os.environ

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
            submitted_prompt="#_x\nplease",
            local_macros=first.local_macros,
        )

    assert LOCAL_MACROS_ENV in captured
    with patch.dict(os.environ, captured, clear=False):
        second = run_extract("#_x\nplease")

    assert set(second.local_macros) == {"_x"}
    assert second.local_macros["_x"].content == "expanded body"
    assert json.loads((artifacts / "agent_meta.json").read_text(encoding="utf-8"))
