"""Local-macros handling across runner-code refresh."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.run_agent_runner_refresh import (
    RUNNER_CODE_REFRESHED_ENV,
    refresh_runner_code_after_wait,
)


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
