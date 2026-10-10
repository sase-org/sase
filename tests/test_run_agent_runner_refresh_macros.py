"""Local-macros handling across runner-code refresh."""

from __future__ import annotations

import os
import sys
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
