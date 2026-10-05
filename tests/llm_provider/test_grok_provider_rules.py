"""GrokProvider `--rules` delivery tests."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.feature_flags import override_flags
from sase.llm_provider.grok import (
    _GROK_RULES_ARGV_BYTE_LIMIT,
    _GROK_SINGLE_TURN_DIRECTIVE,
    _grok_rules_delivery_enabled,
    _grok_rules_text,
    GrokProvider,
)
from sase.llm_provider.types import LLMInvocationError

from ._grok_provider_core_helpers import (
    clear_grok_env_vars,
    invoke_and_capture,
    require_grok_build,
)

_MANAGED_AGENTS_BODY = """\
# Fake Project

Project instructions for the managed-project fixture.
"""

_HOME_AGENTS_H1 = "# Fake Home"


@pytest.fixture(autouse=True)
def _clear_grok_env(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_grok_env_vars(monkeypatch)


def _make_managed_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    agents_body: str = _MANAGED_AGENTS_BODY,
) -> Path:
    """Point rule-text resolution at a fake SASE-managed project."""
    proj = tmp_path / "proj"
    proj.mkdir(exist_ok=True)
    (proj / "AGENTS.md").write_text(agents_body, encoding="utf-8")
    monkeypatch.setattr(
        "sase.feature_flags.managed.project_is_sase_managed",
        lambda cwd=None: True,
    )
    monkeypatch.setattr(
        "sase.content_layout.discover_project_root",
        lambda start=None: proj,
    )
    return proj


def test_grok_directive_opens_with_grok_marker() -> None:
    assert _GROK_SINGLE_TURN_DIRECTIVE.startswith(
        "SASE single-turn instructions for Grok:"
    )


def test_grok_rules_delivery_defaults_on() -> None:
    assert _grok_rules_delivery_enabled() is True


def test_grok_rules_carries_directive_and_project_agents_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "AGENTS.md").write_text(
        f"{_HOME_AGENTS_H1}\n\nHome instructions that must never ship.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))
    _make_managed_project(tmp_path, monkeypatch)

    rules = _grok_rules_text(tmp_path / "proj")

    assert rules == f"{_GROK_SINGLE_TURN_DIRECTIVE}\n\n{_MANAGED_AGENTS_BODY}"
    assert rules.count("# Fake Project") == 1
    assert _HOME_AGENTS_H1 not in rules


def test_grok_rules_non_managed_project_gets_directive_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.feature_flags.managed.project_is_sase_managed",
        lambda cwd=None: False,
    )

    assert _grok_rules_text(tmp_path) == _GROK_SINGLE_TURN_DIRECTIVE


def test_grok_command_appends_rules_once_before_extra_args(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _make_managed_project(tmp_path, monkeypatch)
    monkeypatch.setenv("SASE_GROK_LARGE_ARGS", "--disable-web-search")

    with override_flags(grok_rules_delivery=True):
        cmd, _, _ = invoke_and_capture(GrokProvider(), monkeypatch)

    assert cmd.count("--rules") == 1
    rules = cmd[cmd.index("--rules") + 1]
    assert rules == f"{_GROK_SINGLE_TURN_DIRECTIVE}\n\n{_MANAGED_AGENTS_BODY}"
    assert "--trust" not in cmd
    assert "GROK_CLAUDE_AGENTS_ENABLED" not in " ".join(cmd)
    assert cmd.index("--rules") < cmd.index("--disable-web-search")


def test_grok_command_non_managed_project_sends_directive_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.feature_flags.managed.project_is_sase_managed",
        lambda cwd=None: False,
    )

    with override_flags(grok_rules_delivery=True):
        cmd, _, _ = invoke_and_capture(GrokProvider(), monkeypatch)

    assert cmd.count("--rules") == 1
    assert cmd[cmd.index("--rules") + 1] == _GROK_SINGLE_TURN_DIRECTIVE


def test_grok_rules_reach_every_continuation_cycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _make_managed_project(tmp_path, monkeypatch)
    seen_argvs: list[list[str]] = []

    def _fake_run(
        args: list[str],
        prompt: str,
        suppress_output: bool,
    ) -> tuple[str, str, int, dict[str, int]]:
        del prompt, suppress_output
        seen_argvs.append(list(args))
        if len(seen_argvs) == 1:
            GrokProvider._pending_interrupt_message = "keep going"
            return ("first pass", "", -15, {"input_tokens": 2})
        return ("second pass", "", 0, {"output_tokens": 3})

    provider = GrokProvider()
    try:
        with (
            override_flags(grok_rules_delivery=True),
            patch("sase.llm_provider.grok.provider_timer"),
            patch.object(GrokProvider, "_run_subprocess", side_effect=_fake_run),
        ):
            provider.invoke("original task", model_tier="large", suppress_output=True)
    finally:
        provider._pending_interrupt_message = None

    assert len(seen_argvs) == 2
    expected = f"{_GROK_SINGLE_TURN_DIRECTIVE}\n\n{_MANAGED_AGENTS_BODY}"
    for argv in seen_argvs:
        assert argv.count("--rules") == 1
        assert argv[argv.index("--rules") + 1] == expected


def test_grok_rules_over_limit_raises_actionable_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proj = _make_managed_project(tmp_path, monkeypatch)
    oversized = "# Big\n\n" + ("x" * (_GROK_RULES_ARGV_BYTE_LIMIT + 1)) + "\n"
    (proj / "AGENTS.md").write_text(oversized, encoding="utf-8")

    with pytest.raises(LLMInvocationError, match=r"too large.*byte guard") as excinfo:
        _grok_rules_text(proj)

    message = str(excinfo.value)
    assert str(proj / "AGENTS.md") in message
    assert "--rules" in message


def test_grok_flag_off_omits_rules_entirely(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _make_managed_project(tmp_path, monkeypatch)

    with override_flags(grok_rules_delivery=False):
        cmd, _, _ = invoke_and_capture(GrokProvider(), monkeypatch)

    assert "--rules" not in cmd
    assert "--trust" not in cmd


def test_grok_flag_off_delivers_todays_argv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _make_managed_project(tmp_path, monkeypatch)

    with override_flags(grok_rules_delivery=False):
        cmd, _, _ = invoke_and_capture(GrokProvider(), monkeypatch)

    assert cmd[:2] == ["/opt/grok/bin/grok", "--prompt-file"]
    for flag in (
        "--no-plan",
        "--no-ask-user",
        "--no-auto-update",
        "--no-leader",
    ):
        assert flag in cmd


def test_grok_cli_parse_probe_accepts_rules_flag(tmp_path: Path) -> None:
    grok = require_grok_build()
    result = subprocess.run(
        [
            grok,
            "--prompt-file",
            "/dev/stdin",
            "--output-format",
            "streaming-messages-json",
            "--permission-mode",
            "bypassPermissions",
            "--model",
            "definitely-not-a-model",
            "--cwd",
            str(tmp_path),
            "--rules",
            "SASE single-turn instructions for Grok: parse probe.",
        ],
        input="parse-probe",
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    output = f"{result.stdout}\n{result.stderr}"

    assert result.returncode != 0
    assert "unexpected argument" not in output
