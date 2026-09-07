from __future__ import annotations

from pathlib import Path

import pytest

from sase.diagnostics import DiagnosticCheck
from sase.doctor.checks_dispatch import dispatch_check_specs
from tests.conftest import redirect_sase_home


def _pin() -> str:
    return "sase_inst_v1_" + "a" * 64


def _run_dispatch_check(check_id: str) -> DiagnosticCheck:
    specs = dispatch_check_specs(object())  # type: ignore[arg-type]
    return next(spec.runner() for spec in specs if spec.id == check_id)


@pytest.fixture
def isolated_dispatch_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    from sase.config import core as config_core

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setattr(config_core, "CONFIG_DIR", config_dir)
    config_core.clear_config_cache()
    return config_dir


def test_dispatch_config_check_is_offline_with_no_machines(
    isolated_dispatch_config: Path,
) -> None:
    check = _run_dispatch_check("dispatch.config")

    assert check.status == "OK"
    assert check.data["remote_dispatch_enabled"] is False


def test_dispatch_credentials_reports_missing_local_ref(
    isolated_dispatch_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (isolated_dispatch_config / "sase.yml").write_text(
        "\n".join(
            [
                "dispatch:",
                "  machines:",
                "    alpha:",
                "      provider: builtin@https",
                "      endpoint: https://fleet.example.test",
                "      credential_ref: fleet:alpha",
                f"      installation_pin: {_pin()}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sase.doctor.checks_dispatch.validate_connection_plan",
        lambda record: (),
    )

    check = _run_dispatch_check("dispatch.credentials")

    assert check.status == "ERROR"
    assert "credential ref fleet:alpha is missing" in check.details[0]


def test_dispatch_live_skips_when_flag_off(
    isolated_dispatch_config: Path,
) -> None:
    check = _run_dispatch_check("dispatch.live")

    assert check.status == "SKIP"
    assert "remote_dispatch is disabled" in check.summary
