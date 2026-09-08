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
    assert check.data["machine_count"] == 0


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
        lambda record, **kwargs: (),
    )

    check = _run_dispatch_check("dispatch.credentials")

    assert check.status == "ERROR"
    assert "credential ref fleet:alpha is missing" in check.details[0]


def test_dispatch_live_skips_with_no_machines_configured(
    isolated_dispatch_config: Path,
) -> None:
    check = _run_dispatch_check("dispatch.live")

    assert check.status == "SKIP"
    assert "no remote machines are configured" in check.summary


def test_dispatch_config_reports_provider_not_installed(
    isolated_dispatch_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (isolated_dispatch_config / "sase.yml").write_text(
        "\n".join(
            [
                "dispatch:",
                "  machines:",
                "    alpha:",
                "      provider: acme@tunnel",
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
        lambda record, **kwargs: (),
    )

    check = _run_dispatch_check("dispatch.config")

    assert check.status == "ERROR"
    assert any(
        "provider acme@tunnel is not installed" in detail for detail in check.details
    )


def test_dispatch_config_reports_disabled_provider(
    isolated_dispatch_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (isolated_dispatch_config / "sase.yml").write_text(
        "\n".join(
            [
                "dispatch:",
                "  providers:",
                "    builtin@https: false",
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
        lambda record, **kwargs: (),
    )

    check = _run_dispatch_check("dispatch.config")

    assert check.status == "ERROR"
    assert any(
        "provider builtin@https is disabled" in detail for detail in check.details
    )
