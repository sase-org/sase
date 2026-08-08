"""Tests for Phase 3 doctor provider checks."""

from __future__ import annotations

import stat
from pathlib import Path

from sase.doctor.checks_providers import (
    _check_llm_auth,
    _check_llm_default,
    _check_llm_registry,
    provider_check_specs,
    setup_hint,
)
from sase.doctor.runner import DoctorContext


def _payload() -> dict[str, object]:
    return {
        "providers": {
            "codex": {
                "known_model_names": ["gpt-5.6-sol", "gpt-5.5"],
                "autodetect_cli_name": "codex",
                "model_resolutions": {"large": "gpt-5.6-sol"},
            }
        },
        "autodetect_candidates": [
            {"priority": 10, "provider": "codex", "cli_name": "codex"}
        ],
    }


def _auth_payload(
    *,
    credential_paths: list[str] | None = None,
    env_vars: list[str] | None = None,
) -> dict[str, object]:
    return {
        "providers": {
            "codex": {
                "known_model_names": ["gpt-5.6-sol", "gpt-5.5"],
                "autodetect_cli_name": "codex",
                "auth_evidence": {
                    "credential_paths": credential_paths
                    if credential_paths is not None
                    else ["~/.codex/auth.json"],
                    "api_key_env_vars": env_vars
                    if env_vars is not None
                    else ["OPENAI_API_KEY"],
                },
                "model_resolutions": {"large": "gpt-5.6-sol"},
            }
        },
        "autodetect_candidates": [
            {"priority": 10, "provider": "codex", "cli_name": "codex"}
        ],
    }


def _autodetect_payload() -> dict[str, object]:
    return {
        "providers": {
            "codex": {
                "known_model_names": ["gpt-5.6-sol", "gpt-5.5"],
                "autodetect_cli_name": "codex",
                "model_resolutions": {"large": "gpt-5.6-sol"},
            },
            "gemini": {
                "known_model_names": ["gemini-3-flash-preview"],
                "autodetect_cli_name": "gemini",
                "model_resolutions": {"large": "gemini-3-flash-preview"},
            },
        },
        "autodetect_candidates": [
            {"priority": 10, "provider": "codex", "cli_name": "codex"},
            {"priority": 30, "provider": "gemini", "cli_name": "gemini"},
        ],
    }


def _agy_payload() -> dict[str, object]:
    return {
        "providers": {
            "agy": {
                "known_model_names": [
                    "gemini-3.6-flash-high",
                    "gemini-3.6-flash-low",
                ],
                "autodetect_cli_name": "agy",
                "model_resolutions": {
                    "large": "gemini-3.6-flash-high",
                    "small": "gemini-3.6-flash-low",
                },
            }
        },
        "autodetect_candidates": [
            {"priority": 30, "provider": "agy", "cli_name": "agy"}
        ],
    }


def _fakey_payload() -> dict[str, object]:
    return {
        "providers": {
            "fakey": {
                "known_model_names": ["fakey-large", "fakey-small"],
                "autodetect_cli_name": "fakey",
                "auth_evidence": {
                    "credential_paths": [],
                    "api_key_env_vars": [],
                    "auth_not_required": True,
                },
                "model_resolutions": {
                    "large": "fakey-large",
                    "small": "fakey-small",
                },
            }
        },
        "autodetect_candidates": [
            {"priority": 1000, "provider": "fakey", "cli_name": "fakey"}
        ],
    }


def _context(tmp_path: Path, env: dict[str, str] | None = None) -> DoctorContext:
    return DoctorContext(
        cwd=tmp_path,
        project=None,
        sase_home=tmp_path / ".sase",
        env=env or {},
    )


def _patch_codex_selection(monkeypatch, payload: dict[str, object]) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_providers.llm_registry.get_llm_metadata_payload",
        lambda: payload,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.llm_registry.get_default_provider_name",
        lambda: "codex",
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.get_llm_provider_config",
        lambda: {"provider": "codex"},
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.get_active_temporary_override",
        lambda: None,
    )


def test_provider_check_specs_registers_llm_auth(tmp_path) -> None:
    ids = [spec.id for spec in provider_check_specs(_context(tmp_path))]

    assert ids == ["llm.registry", "llm.default", "llm.auth", "llm.model_advisory"]


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


def test_llm_default_errors_when_selected_cli_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_providers.llm_registry.get_llm_metadata_payload",
        _payload,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.llm_registry.get_default_provider_name",
        lambda: "codex",
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.get_llm_provider_config",
        lambda: {"provider": "codex"},
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.get_active_temporary_override",
        lambda: None,
    )
    monkeypatch.setattr("sase.doctor.checks_providers.shutil.which", lambda _: None)

    check = _check_llm_default(_context(tmp_path))

    assert check.status == "ERROR"
    assert "codex" in check.summary
    assert "executable" in check.summary
    assert "SASE_CODEX_PATH" in check.next_steps[0]
    assert check.data["selection_source"] == "config"
    assert check.data["auth_status"] == "not_verified"
    assert check.data["auth_verified"] is False
    assert check.data["setup_hint"]["tool"] == "Codex CLI"


def test_llm_default_errors_when_autodetect_finds_no_cli(monkeypatch, tmp_path) -> None:
    def fail_default() -> str:
        raise RuntimeError("No LLM provider is available")

    monkeypatch.setattr(
        "sase.doctor.checks_providers.llm_registry.get_llm_metadata_payload",
        _autodetect_payload,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.llm_registry.get_default_provider_name",
        fail_default,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.get_llm_provider_config",
        lambda: {},
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.get_active_temporary_override",
        lambda: None,
    )
    monkeypatch.setattr("sase.doctor.checks_providers.shutil.which", lambda _: None)

    check = _check_llm_default(_context(tmp_path))

    readiness = {row["provider"]: row for row in check.data["provider_readiness"]}
    assert check.status == "ERROR"
    assert "no usable default" in check.summary
    assert check.data["provider"] is None
    assert check.data["selection_source"] == "autodetect"
    assert readiness["codex"]["ready"] is False
    assert readiness["gemini"]["cli_name"] == "gemini"
    assert readiness["gemini"]["ready"] is False
    assert "Codex CLI setup" in check.next_steps[0]
    assert "auth: not verified" in check.details[-1]


def test_llm_default_accepts_configured_executable_path(monkeypatch, tmp_path) -> None:
    exe = tmp_path / "codex"
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(
        "sase.doctor.checks_providers.llm_registry.get_llm_metadata_payload",
        _payload,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.llm_registry.get_default_provider_name",
        lambda: "codex",
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.get_llm_provider_config",
        lambda: {"provider": "codex"},
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.get_active_temporary_override",
        lambda: None,
    )

    check = _check_llm_default(_context(tmp_path, {"SASE_CODEX_PATH": str(exe)}))

    assert check.status == "OK"
    assert check.data["configured_command"] == str(exe)
    assert check.data["command"] == str(exe)
    assert check.data["executable"] == str(exe)
    assert check.data["ready"] is True
    assert check.data["auth_status"] == "not_verified"


def test_llm_default_errors_when_agy_cli_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_providers.llm_registry.get_llm_metadata_payload",
        _agy_payload,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.llm_registry.get_default_provider_name",
        lambda: "agy",
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.get_llm_provider_config",
        lambda: {"provider": "agy"},
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.get_active_temporary_override",
        lambda: None,
    )
    monkeypatch.setattr("sase.doctor.checks_providers.shutil.which", lambda _: None)

    check = _check_llm_default(_context(tmp_path))

    assert check.status == "ERROR"
    assert "agy" in check.summary
    assert "executable" in check.summary
    # The path override env var is derived from the provider name.
    assert check.data["path_env"] == "SASE_AGY_PATH"
    assert "SASE_AGY_PATH" in check.next_steps[0]
    assert check.data["selection_source"] == "config"
    assert check.data["auth_status"] == "not_verified"
    assert check.data["auth_verified"] is False
    assert check.data["setup_hint"]["tool"] == "Antigravity CLI"
    assert "antigravity.google" in check.data["setup_hint"]["install"]


def test_llm_default_accepts_configured_agy_executable_path(
    monkeypatch, tmp_path
) -> None:
    exe = tmp_path / "agy"
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(
        "sase.doctor.checks_providers.llm_registry.get_llm_metadata_payload",
        _agy_payload,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.llm_registry.get_default_provider_name",
        lambda: "agy",
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.get_llm_provider_config",
        lambda: {"provider": "agy"},
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.get_active_temporary_override",
        lambda: None,
    )

    check = _check_llm_default(_context(tmp_path, {"SASE_AGY_PATH": str(exe)}))

    assert check.status == "OK"
    assert check.data["path_env"] == "SASE_AGY_PATH"
    assert check.data["configured_command"] == str(exe)
    assert check.data["executable"] == str(exe)
    assert check.data["ready"] is True
    # Model resolutions for tiers are reported so
    # `sase doctor -C llm.default -v` can show them.
    assert check.data["model_resolutions"]["large"] == "gemini-3.6-flash-high"
    assert check.data["auth_status"] == "not_verified"


def test_llm_auth_ok_when_api_key_env_var_present(monkeypatch, tmp_path) -> None:
    _patch_codex_selection(monkeypatch, _auth_payload())
    monkeypatch.setattr(
        "sase.doctor.checks_providers.shutil.which",
        lambda _: "/usr/bin/codex",
    )

    check = _check_llm_auth(
        _context(tmp_path, {"HOME": str(tmp_path), "OPENAI_API_KEY": "sk-secret"})
    )

    assert check.status == "OK"
    assert check.data["auth_status"] == "evidence_found"
    assert check.data["auth_verified"] is False
    assert check.data["evidence_found"] is True
    assert check.data["evidence"][0]["type"] == "env_var"
    assert check.data["evidence"][0]["name"] == "OPENAI_API_KEY"
    assert "sk-secret" not in str(check.data)
    assert "sk-secret" not in " ".join(check.details)


def test_llm_auth_ok_when_credential_path_exists(monkeypatch, tmp_path) -> None:
    home = tmp_path / "home"
    auth_file = home / ".codex" / "auth.json"
    auth_file.parent.mkdir(parents=True)
    auth_file.write_text("{}\n", encoding="utf-8")
    payload = _auth_payload(
        credential_paths=["$CODEX_HOME/auth.json", "~/.codex/auth.json"]
    )
    _patch_codex_selection(monkeypatch, payload)
    monkeypatch.setattr(
        "sase.doctor.checks_providers.shutil.which",
        lambda _: "/usr/bin/codex",
    )

    check = _check_llm_auth(_context(tmp_path, {"HOME": str(home)}))

    assert check.status == "OK"
    assert check.data["auth_status"] == "evidence_found"
    assert check.data["evidence"][0]["type"] == "path"
    assert check.data["evidence"][0]["path"] == str(auth_file)
    assert "$CODEX_HOME/auth.json" in check.data["skipped_path_patterns"]
    assert check.data["auth_verified"] is False


def test_llm_auth_warns_when_cli_present_but_no_evidence(monkeypatch, tmp_path) -> None:
    _patch_codex_selection(monkeypatch, _auth_payload())
    monkeypatch.setattr(
        "sase.doctor.checks_providers.shutil.which",
        lambda _: "/usr/bin/codex",
    )

    check = _check_llm_auth(_context(tmp_path, {"HOME": str(tmp_path / "home")}))

    assert check.status == "WARN"
    assert "no offline auth evidence" in check.summary
    assert check.data["auth_status"] == "missing_evidence"
    assert check.data["evidence_found"] is False
    assert check.data["checked_env_vars"] == ("OPENAI_API_KEY",)
    assert "Codex CLI setup" in check.next_steps[0]
    assert check.data["auth_verified"] is False


def test_llm_auth_skips_when_selected_cli_missing(monkeypatch, tmp_path) -> None:
    _patch_codex_selection(monkeypatch, _auth_payload())
    monkeypatch.setattr("sase.doctor.checks_providers.shutil.which", lambda _: None)

    check = _check_llm_auth(_context(tmp_path, {"HOME": str(tmp_path)}))

    assert check.status == "SKIP"
    assert "executable is missing" in check.summary
    assert check.data["auth_status"] == "skipped_cli_missing"
    assert check.data["auth_verified"] is False
    assert check.next_steps[0] == "Fix `llm.default` first."


def test_llm_auth_ok_when_provider_requires_no_auth(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_providers.llm_registry.get_llm_metadata_payload",
        _fakey_payload,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.llm_registry.get_default_provider_name",
        lambda: "fakey",
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.get_llm_provider_config",
        lambda: {"provider": "fakey"},
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.get_active_temporary_override",
        lambda: None,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.shutil.which", lambda _: "/venv/bin/fakey"
    )

    check = _check_llm_auth(_context(tmp_path))

    assert check.status == "OK"
    assert check.data["auth_status"] == "not_required"
    assert check.data["auth_required"] is False
    assert check.data["evidence_found"] is False
    assert "requires no authentication" in check.summary
