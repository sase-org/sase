"""Tests for Phase 3 doctor provider check registration and setup hints."""

from __future__ import annotations

from pathlib import Path

from sase.agent_clis.models import AgentCliStatus, InstallMethod, ShadowInstall
from sase.doctor.checks_providers import (
    _check_llm_cli_shadow,
    _check_llm_registry,
    provider_check_specs,
    setup_hint,
)
from sase.doctor.runner import DoctorContext


def _context(tmp_path: Path, env: dict[str, str] | None = None) -> DoctorContext:
    return DoctorContext(
        cwd=tmp_path,
        project=None,
        sase_home=tmp_path / ".sase",
        env=env or {},
    )


def test_provider_check_specs_registers_llm_auth(tmp_path) -> None:
    ids = [spec.id for spec in provider_check_specs(_context(tmp_path))]

    assert ids == [
        "llm.registry",
        "llm.model_policy",
        "llm.default",
        "llm.auth",
        "llm.cli_shadow",
        "llm.model_advisory",
        "llm.usage",
    ]


def _cli_status(
    *,
    other_version: str | None = None,
    other_path: str = "/usr/local/bin/codex",
) -> AgentCliStatus:
    other_installs = ()
    if other_version is not None:
        other_installs = (ShadowInstall(executable=other_path, version=other_version),)
    return AgentCliStatus(
        name="codex",
        display_name="Codex CLI",
        binary="codex",
        executable="/home/user/.nvm/bin/codex",
        installed_version="0.163.0",
        latest_version=None,
        install_method=InstallMethod.NPM,
        update_available=False,
        docs_url=None,
        install_hint="npm install -g @openai/codex",
        other_installs=other_installs,
    )


def test_cli_shadow_check_warns_on_version_skew(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_providers.llm_registry.get_llm_metadata_payload",
        lambda: {"providers": {"codex": {"autodetect_cli_name": "codex"}}},
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.detect_agent_cli_statuses",
        lambda *_args, **_kwargs: (_cli_status(other_version="0.128.0"),),
    )

    check = _check_llm_cli_shadow(_context(tmp_path))

    assert check.status == "WARN"
    assert check.id == "llm.cli_shadow"
    assert "codex" in check.summary
    assert any("0.128.0" in detail for detail in check.details)
    assert any("SASE_CODEX_PATH" in detail for detail in check.details)
    assert any("sase agent-cli list" in step for step in check.next_steps)


def test_cli_shadow_check_passes_without_version_skew(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_providers.llm_registry.get_llm_metadata_payload",
        lambda: {"providers": {"codex": {"autodetect_cli_name": "codex"}}},
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.detect_agent_cli_statuses",
        lambda *_args, **_kwargs: (_cli_status(other_version="0.163.0"),),
    )

    check = _check_llm_cli_shadow(_context(tmp_path))

    assert check.status == "OK"
    assert check.details == ()


def test_setup_hint_prefers_enriched_provider_metadata() -> None:
    hint = setup_hint(
        "codex",
        {
            "install": {
                "manager": "npm",
                "package": "replacement-codex",
                "display_name": "Replacement Codex",
                "docs_url": "https://example.test/codex",
            }
        },
    )

    assert hint == {
        "tool": "Replacement Codex",
        "install": "npm install -g replacement-codex",
        "auth": "run `codex login`",
        "docs_url": "https://example.test/codex",
    }


def test_setup_hint_points_script_installs_at_the_install_subcommand() -> None:
    """A docs URL must not override the actionable install command."""
    hint = setup_hint(
        "muse",
        {
            "install": {
                "manager": "script",
                "display_name": "Muse Code",
                "docs_url": "https://example.test/muse",
                "install_script_url": "https://example.test/install.sh",
            }
        },
    )

    assert hint == {
        "tool": "Muse Code",
        "install": "run `sase agent-cli install muse`",
        "auth": "run `muse login`, or set META_API_KEY",
        "docs_url": "https://example.test/muse",
    }


def test_setup_hint_falls_back_to_grok_metadata_when_unenriched() -> None:
    hint = setup_hint("grok")

    assert hint == {
        "tool": "Grok Build",
        "install": "npm install -g @xai-official/grok",
        "auth": (
            "run `grok login` (or `grok login --device-code` on a headless "
            "host), or set XAI_API_KEY"
        ),
    }


def test_llm_registry_reports_metadata_load_failure(monkeypatch) -> None:
    def fail() -> dict[str, object]:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "sase.doctor.checks_providers.llm_registry.get_llm_metadata_payload",
        fail,
    )

    check = _check_llm_registry()

    assert check.status == "ERROR"
    assert "metadata could not be loaded" in check.summary
    assert "boom" in check.details[0]
