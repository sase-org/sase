"""Background usage-collection eligibility, including Codex CLI resolution.

Codex's launcher and usage collector both resolve the Codex executable through
``resolve_codex_executable()`` (``SASE_CODEX_PATH``, then ``PATH``, then
``NVM_BIN/codex``). Eligibility gating must recognize the same executable, or a
Codex install that only exists through ``NVM_BIN`` never reaches the usage
indicator even though invocation and collection both work.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.llm_provider.usage.refresh import (
    _provider_cli_ready,
    eligible_usage_providers,
)
from tests.llm_provider._provider_config_helpers import mock_provider_config


def _payload(providers: dict[str, dict[str, object]]) -> dict[str, object]:
    return {"providers": providers}


def _codex_metadata(
    *, cli_name: object = "codex", probe: bool = True
) -> dict[str, object]:
    metadata: dict[str, object] = {"usage_capabilities": {"probe": probe}}
    if cli_name is not None:
        metadata["autodetect_cli_name"] = cli_name
    return metadata


def _write_executable(path: Path) -> Path:
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)
    return path


def _isolate_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point PATH at an empty directory so ``codex`` cannot resolve from PATH."""
    empty = tmp_path / "empty-path"
    empty.mkdir(exist_ok=True)
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.delenv("SASE_CODEX_PATH", raising=False)
    monkeypatch.delenv("NVM_BIN", raising=False)


@pytest.fixture
def _isolated_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the registry to a single deterministic Codex entry for eligibility tests."""
    monkeypatch.setattr(
        "sase.llm_provider.registry.registered_provider_names",
        lambda: ["codex"],
    )
    monkeypatch.setattr(
        "sase.llm_provider.registry.model_picker_hidden_provider_names",
        lambda: frozenset(),
    )
    monkeypatch.setattr(
        "sase.llm_provider.usage.refresh._referenced_provider_ids",
        lambda: set(),
    )


def _enable_codex_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_provider_config(
        monkeypatch,
        {"usage_metrics": {"enabled": True, "providers": {"codex": {"enabled": True}}}},
    )


class TestEligibleUsageProvidersCodexNvmFallback:
    """Focused regression for the public eligibility entry point."""

    def test_codex_is_eligible_through_nvm_fallback_when_path_is_empty(
        self,
        _isolated_registry: None,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(
            "sase.llm_provider.registry.get_llm_metadata_payload",
            lambda: _payload({"codex": _codex_metadata()}),
        )
        _enable_codex_collection(monkeypatch)
        _isolate_path(monkeypatch, tmp_path)
        nvm_bin = tmp_path / "nvm-bin"
        nvm_bin.mkdir()
        _write_executable(nvm_bin / "codex")
        monkeypatch.setenv("NVM_BIN", str(nvm_bin))

        assert eligible_usage_providers() == ("codex",)


class TestProviderCliReadyCodexBoundaries:
    """Availability boundaries for Codex's resolver-backed readiness check."""

    def test_nvm_fallback_succeeds(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _isolate_path(monkeypatch, tmp_path)
        nvm_bin = tmp_path / "nvm-bin"
        nvm_bin.mkdir()
        _write_executable(nvm_bin / "codex")
        monkeypatch.setenv("NVM_BIN", str(nvm_bin))

        assert _provider_cli_ready("codex", _codex_metadata()) is True

    def test_ordinary_path_lookup_succeeds(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        _write_executable(bin_dir / "codex")
        monkeypatch.setenv("PATH", str(bin_dir))
        monkeypatch.delenv("SASE_CODEX_PATH", raising=False)
        monkeypatch.delenv("NVM_BIN", raising=False)

        assert _provider_cli_ready("codex", _codex_metadata()) is True

    def test_explicit_override_wins_over_path_and_nvm(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path_bin = tmp_path / "bin"
        path_bin.mkdir()
        _write_executable(path_bin / "codex")
        monkeypatch.setenv("PATH", str(path_bin))
        nvm_bin = tmp_path / "nvm-bin"
        nvm_bin.mkdir()
        _write_executable(nvm_bin / "codex")
        monkeypatch.setenv("NVM_BIN", str(nvm_bin))
        override = _write_executable(tmp_path / "override-codex")
        monkeypatch.setenv("SASE_CODEX_PATH", str(override))

        assert _provider_cli_ready("codex", _codex_metadata()) is True

        from sase.llm_provider.codex import resolve_codex_executable

        assert resolve_codex_executable() == str(override)

    def test_explicit_invalid_override_does_not_fall_through_to_nvm(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _isolate_path(monkeypatch, tmp_path)
        nvm_bin = tmp_path / "nvm-bin"
        nvm_bin.mkdir()
        _write_executable(nvm_bin / "codex")
        monkeypatch.setenv("NVM_BIN", str(nvm_bin))
        monkeypatch.setenv("SASE_CODEX_PATH", str(tmp_path / "missing-codex"))

        assert _provider_cli_ready("codex", _codex_metadata()) is False

    def test_missing_path_and_nvm_candidates_stay_unavailable(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _isolate_path(monkeypatch, tmp_path)

        assert _provider_cli_ready("codex", _codex_metadata()) is False


class TestProviderCliReadyGenericMetadataPath:
    """The generic override/metadata path must keep working for other plugins."""

    def test_generic_provider_uses_metadata_cli_name(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        _write_executable(bin_dir / "some-cli")
        monkeypatch.setenv("PATH", str(bin_dir))
        monkeypatch.delenv("SASE_OTHER_PATH", raising=False)

        assert _provider_cli_ready("other", {"autodetect_cli_name": "some-cli"}) is True

    def test_generic_provider_missing_cli_is_not_ready(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("PATH", str(tmp_path))
        monkeypatch.delenv("SASE_OTHER_PATH", raising=False)

        assert (
            _provider_cli_ready("other", {"autodetect_cli_name": "missing-cli"})
            is False
        )

    def test_generic_provider_without_declared_cli_is_always_ready(self) -> None:
        assert _provider_cli_ready("other", {}) is True

    def test_generic_provider_explicit_override_env_var(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        override = _write_executable(tmp_path / "override-cli")
        monkeypatch.setenv("SASE_OTHER_PATH", str(override))

        assert _provider_cli_ready("other", {"autodetect_cli_name": "some-cli"}) is True


class TestEligibleUsageProvidersExclusionRules:
    """Codex's resolver fix must not disturb the surrounding eligibility gates."""

    def _ready_codex_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        _write_executable(bin_dir / "codex")
        monkeypatch.setenv("PATH", str(bin_dir))
        monkeypatch.delenv("SASE_CODEX_PATH", raising=False)
        monkeypatch.delenv("NVM_BIN", raising=False)

    def test_hidden_provider_is_excluded(
        self,
        _isolated_registry: None,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(
            "sase.llm_provider.registry.model_picker_hidden_provider_names",
            lambda: frozenset({"codex"}),
        )
        monkeypatch.setattr(
            "sase.llm_provider.registry.get_llm_metadata_payload",
            lambda: _payload({"codex": _codex_metadata()}),
        )
        self._ready_codex_env(monkeypatch, tmp_path)
        _enable_codex_collection(monkeypatch)

        assert eligible_usage_providers() == ()

    def test_non_probing_provider_is_excluded(
        self,
        _isolated_registry: None,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(
            "sase.llm_provider.registry.get_llm_metadata_payload",
            lambda: _payload({"codex": _codex_metadata(probe=False)}),
        )
        self._ready_codex_env(monkeypatch, tmp_path)
        _enable_codex_collection(monkeypatch)

        assert eligible_usage_providers() == ()

    def test_unreferenced_and_not_explicitly_enabled_is_excluded(
        self,
        _isolated_registry: None,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(
            "sase.llm_provider.registry.get_llm_metadata_payload",
            lambda: _payload({"codex": _codex_metadata()}),
        )
        self._ready_codex_env(monkeypatch, tmp_path)
        mock_provider_config(monkeypatch, {"usage_metrics": {"enabled": True}})

        assert eligible_usage_providers() == ()

    def test_collection_disabled_provider_is_excluded_even_when_referenced(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(
            "sase.llm_provider.registry.registered_provider_names",
            lambda: ["codex"],
        )
        monkeypatch.setattr(
            "sase.llm_provider.registry.model_picker_hidden_provider_names",
            lambda: frozenset(),
        )
        monkeypatch.setattr(
            "sase.llm_provider.usage.refresh._referenced_provider_ids",
            lambda: {"codex"},
        )
        monkeypatch.setattr(
            "sase.llm_provider.registry.get_llm_metadata_payload",
            lambda: _payload({"codex": _codex_metadata()}),
        )
        self._ready_codex_env(monkeypatch, tmp_path)
        mock_provider_config(
            monkeypatch,
            {
                "usage_metrics": {
                    "enabled": True,
                    "providers": {"codex": {"enabled": False}},
                }
            },
        )

        assert eligible_usage_providers() == ()

    def test_explicit_enablement_includes_an_unreferenced_provider(
        self,
        _isolated_registry: None,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(
            "sase.llm_provider.registry.get_llm_metadata_payload",
            lambda: _payload({"codex": _codex_metadata()}),
        )
        self._ready_codex_env(monkeypatch, tmp_path)
        _enable_codex_collection(monkeypatch)

        assert eligible_usage_providers() == ("codex",)
