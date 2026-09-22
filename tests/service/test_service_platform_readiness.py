"""Service-platform readiness warnings and lifecycle-runner guard tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.service.platform import (
    SERVICE_LIFECYCLE_TEST_BLOCK_MESSAGE,
    SERVICE_LIFECYCLE_TEST_OVERRIDE_ENV,
    _readiness_warnings,
    build_native_definition,
    inspect_native_service,
    service_init_plan,
)
from tests.service.service_platform_helpers import (
    _Runner,
    _exe,
    _linux_home,
    _stub_non_ssh_readiness,
)


def test_readiness_warnings_omit_secrets_and_compare_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live_bin = tmp_path / "live"
    live_bin.mkdir()
    binary = live_bin / "codex"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    monkeypatch.setenv("PATH", str(live_bin))
    monkeypatch.setenv("SASE_FEATURE_FLAGS", '{"typed_launch_units": true}')
    monkeypatch.setattr(
        "sase.service.platform.collect_agent_cli_statuses",
        lambda **_k: (
            SimpleNamespace(
                display_name="Codex",
                installed=False,
                binary="codex",
            ),
        ),
    )
    monkeypatch.setattr(
        "sase.integrations.mobile_gateway.load_mobile_gateway_config",
        lambda: SimpleNamespace(command=(str(tmp_path / "missing-gateway"),)),
    )
    warnings = _readiness_warnings(
        {
            "PATH": str(tmp_path / "empty"),
            "OPENAI_API_KEY": "super-secret-token",
        }
    )
    joined = "\n".join(warnings)
    assert "super-secret-token" not in joined
    assert "interactive PATH" in joined
    assert "mobile gateway" in joined
    assert "SASE_FEATURE_FLAGS differ" in joined


def test_readiness_warnings_leave_ssh_to_the_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The capture owns the SSH report, so readiness must not ask the remote again."""
    _stub_non_ssh_readiness(monkeypatch)

    def fail(_env: dict[str, str]) -> str:
        raise AssertionError("_readiness_warnings must not probe the git remote")

    monkeypatch.setattr("sase.service.ssh_agent.probe_git_remote_auth", fail)

    assert _readiness_warnings({"PATH": "/nowhere"}) == ()


def test_init_plan_reports_a_refused_capture_exactly_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setattr("sase.service.platform.platform.system", lambda: "Linux")
    _stub_non_ssh_readiness(monkeypatch)
    probed: list[dict[str, str]] = []

    def denied(env: dict[str, str]) -> str:
        probed.append(env)
        return "denied"

    monkeypatch.setattr("sase.service.ssh_agent.probe_git_remote_auth", denied)

    plan = service_init_plan(
        runner=_Runner(),
        environ={"PATH": "/bin"},
        executable_resolver=lambda: str(_exe(tmp_path)),
    )

    refused = [w for w in plan.warnings if "refused by the git remote" in w]
    assert len(refused) == 1
    assert refused[0].startswith("captured service environment")
    assert len(probed) == 1
    assert plan.status == "needs_attention"


def test_default_runner_refuses_under_pytest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.service import platform as service_platform

    _linux_home(tmp_path, monkeypatch)
    monkeypatch.delenv(SERVICE_LIFECYCLE_TEST_OVERRIDE_ENV, raising=False)
    with patch("sase.service.platform_runner.subprocess.run") as run:
        result = service_platform.default_runner(
            ["systemctl", "--user", "is-active", "sase.service"]
        )
    run.assert_not_called()
    assert result.returncode == 125
    assert SERVICE_LIFECYCLE_TEST_BLOCK_MESSAGE in result.stderr
    definition, _blockers, _exe_info = build_native_definition(
        executable_resolver=lambda: str(_exe(tmp_path)),
    )
    with patch("sase.service.platform_runner.subprocess.run") as run:
        inspection = inspect_native_service(
            definition,
            desired_env={"PATH": "/bin"},
        )
    run.assert_not_called()
    assert inspection.active is False


def test_default_runner_override_allows_isolated_lifecycle_test(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.service import platform as service_platform

    monkeypatch.setenv(SERVICE_LIFECYCLE_TEST_OVERRIDE_ENV, "1")
    with patch("sase.service.platform_runner.subprocess.run") as run:
        run.return_value = SimpleNamespace(returncode=0, stdout="ok\n", stderr="")
        result = service_platform.default_runner(["true"])
    run.assert_called_once()
    assert result.returncode == 0
    assert result.stdout == "ok\n"


def test_readiness_warns_when_shell_and_captured_tmp_roots_differ(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale capture reaps the wrong root; doctor must name both roots."""
    _stub_non_ssh_readiness(monkeypatch)
    monkeypatch.setenv("SASE_TMPDIR", "/shell/cache/sase/tmp")
    monkeypatch.delenv("SASE_HOME", raising=False)

    warnings = _readiness_warnings({"PATH": "/captured/bin"})

    joined = "\n".join(warnings)
    assert "managed tmp root differs" in joined
    assert "/shell/cache/sase/tmp" in joined
    assert "sase service init --yes" in joined


def test_readiness_warns_when_shell_and_captured_home_roots_differ(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_non_ssh_readiness(monkeypatch)
    monkeypatch.setenv("SASE_HOME", "/shell/.sase")
    monkeypatch.delenv("SASE_TMPDIR", raising=False)

    warnings = _readiness_warnings({"PATH": "/captured/bin"})

    assert any("managed tmp root differs" in warning for warning in warnings)


def test_readiness_stays_quiet_when_tmp_roots_agree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_non_ssh_readiness(monkeypatch)
    monkeypatch.setenv("SASE_TMPDIR", "/shared/sase/tmp")
    monkeypatch.delenv("SASE_HOME", raising=False)

    assert (
        _readiness_warnings(
            {"PATH": "/captured/bin", "SASE_TMPDIR": "/shared/sase/tmp"}
        )
        == ()
    )
