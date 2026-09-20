"""Tests for the service-platform doctor check."""

from __future__ import annotations

from types import SimpleNamespace

from sase.doctor.checks_service_platform import check_service_platform


def _plan(
    *,
    blockers: tuple[str, ...] = (),
    actions: tuple[str, ...] = (),
    warnings: tuple[str, ...] = (),
    identity: str = "sase.service",
) -> SimpleNamespace:
    return SimpleNamespace(
        blockers=blockers,
        actions=actions,
        warnings=warnings,
        definition=SimpleNamespace(identity=identity),
    )


def test_service_platform_check_errors_on_blockers(monkeypatch) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_service_platform.service_init_plan",
        lambda **_k: _plan(blockers=("missing stable sase executable",)),
    )
    check = check_service_platform()

    assert check.status == "ERROR"
    assert "missing stable sase executable" in check.details
    assert "super-secret" not in check.summary


def test_service_platform_check_warns_on_drift_without_leaking_secrets(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_service_platform.service_init_plan",
        lambda **_k: _plan(
            actions=("write /tmp/sase.service",),
            warnings=("Codex CLI is not available to the captured service PATH",),
        ),
    )
    check = check_service_platform()

    assert check.status == "WARN"
    joined = "\n".join((check.summary, *check.details))
    assert "write /tmp/sase.service" in joined
    assert "sk-secret" not in joined
    assert "OPENAI_API_KEY=" not in joined


def test_service_platform_check_ok_when_current(monkeypatch) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_service_platform.service_init_plan",
        lambda **_k: _plan(),
    )
    check = check_service_platform()

    assert check.status == "OK"
    assert check.summary == "sase.service is current"
    assert check.data["unit"] == "sase.service"
