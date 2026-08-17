from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests._validate_sase_core_rs_tool_helpers import load_validate_sase_core_rs


pytestmark = pytest.mark.contract


def _write_pyproject(root: Path, dependency: str) -> Path:
    pyproject = root / "pyproject.toml"
    pyproject.write_text(
        f'[project]\ndependencies = ["{dependency}"]\n',
        encoding="utf-8",
    )
    return pyproject


def _write_core_checkout(root: Path, version: str) -> Path:
    core = root / "sase-core"
    core.mkdir()
    (core / "Cargo.toml").write_text(
        f'[workspace.package]\nversion = "{version}"\n',
        encoding="utf-8",
    )
    return core


def test_validate_installed_version_fails_when_below_the_pyproject_floor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validator = load_validate_sase_core_rs()
    monkeypatch.setattr(validator.importlib.metadata, "version", lambda _name: "0.1.0")
    pyproject = _write_pyproject(tmp_path, "sase-core-rs>=0.2.0,<0.3.0")

    assert not validator._validate_installed_version(
        pyproject=pyproject, sase_core_dir=None
    )


def test_validate_installed_version_fails_when_it_disagrees_with_the_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validator = load_validate_sase_core_rs()
    monkeypatch.setattr(validator.importlib.metadata, "version", lambda _name: "0.2.0")
    pyproject = _write_pyproject(tmp_path, "sase-core-rs>=0.2.0,<0.3.0")
    sase_core_dir = _write_core_checkout(tmp_path, "0.2.5")

    assert not validator._validate_installed_version(
        pyproject=pyproject, sase_core_dir=sase_core_dir
    )


def test_validate_installed_version_passes_in_range_and_in_agreement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validator = load_validate_sase_core_rs()
    monkeypatch.setattr(validator.importlib.metadata, "version", lambda _name: "0.2.0")
    pyproject = _write_pyproject(tmp_path, "sase-core-rs>=0.2.0,<0.3.0")
    sase_core_dir = _write_core_checkout(tmp_path, "0.2.0")

    assert validator._validate_installed_version(
        pyproject=pyproject, sase_core_dir=sase_core_dir
    )


def test_validate_installed_version_only_enforces_the_floor_not_the_ceiling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Allow dev builds to run ahead of the published compatibility window."""
    validator = load_validate_sase_core_rs()
    monkeypatch.setattr(validator.importlib.metadata, "version", lambda _name: "0.99.0")
    pyproject = _write_pyproject(tmp_path, "sase-core-rs>=0.2.0,<0.3.0")

    assert validator._validate_installed_version(
        pyproject=pyproject, sase_core_dir=None
    )


def _guard_schema_payload(providers: list[str]) -> dict[str, object]:
    """Build a minimal schema stub shaped like the real ``inhibit_if`` enum."""
    return {
        "properties": {
            "axe": {
                "properties": {
                    "lumberjacks": {
                        "additionalProperties": {
                            "properties": {
                                "chops": {
                                    "items": {
                                        "properties": {
                                            "inhibit_if": {
                                                "oneOf": [
                                                    {
                                                        "type": "array",
                                                        "items": {
                                                            "properties": {
                                                                "provider": {
                                                                    "enum": providers
                                                                }
                                                            }
                                                        },
                                                    }
                                                ]
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }


def _write_guard_schema(tmp_path: Path, providers: list[str] | None = None) -> Path:
    providers = providers or [
        "patch",
        # Legacy alias retained for the ``patch`` provider.
        "changespec",
        "agent_hood",
        "agent_clan",
        "agent_runners",
    ]
    schema_path = tmp_path / "sase.schema.json"
    schema_path.write_text(
        json.dumps(_guard_schema_payload(providers)), encoding="utf-8"
    )
    return schema_path


def _guard_provider_from_request(request: dict[str, object]) -> str:
    axe = request["config"]["axe"]  # type: ignore[index]
    chop = axe["lumberjacks"]["probe"]["chops"][0]  # type: ignore[index]
    return next(iter(chop["inhibit_if"]))


def test_validate_axe_chop_guard_providers_passes_when_core_accepts_every_provider(
    tmp_path: Path,
) -> None:
    validator = load_validate_sase_core_rs()
    schema_path = _write_guard_schema(tmp_path)
    module = SimpleNamespace(
        chop_engine_schema_version=lambda: 1,
        validate_axe_config=lambda _request: [],
    )

    assert validator._validate_axe_chop_guard_providers(module, schema_path=schema_path)


def test_validate_axe_chop_guard_providers_fails_when_core_rejects_agent_runners(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    validator = load_validate_sase_core_rs()
    schema_path = _write_guard_schema(tmp_path)

    def validate_axe_config(request: dict[str, object]) -> list[dict[str, object]]:
        provider = _guard_provider_from_request(request)
        if provider == "agent_runners":
            return [
                {
                    "code": "unknown_guard_provider",
                    "message": "unknown guard provider `agent_runners`",
                }
            ]
        return []

    module = SimpleNamespace(
        chop_engine_schema_version=lambda: 1,
        validate_axe_config=validate_axe_config,
    )

    assert not validator._validate_axe_chop_guard_providers(
        module, schema_path=schema_path
    )
    stderr = capsys.readouterr().err
    assert "] agent_runners(" in stderr


def test_validate_axe_chop_guard_providers_fails_on_schema_drift(
    tmp_path: Path,
) -> None:
    """Fail if the schema advertises a provider the probe table does not cover."""
    validator = load_validate_sase_core_rs()
    schema_path = _write_guard_schema(
        tmp_path,
        providers=[
            "patch",
            # Legacy alias retained for the ``patch`` provider.
            "changespec",
            "agent_hood",
            "agent_clan",
            "agent_runners",
            "mystery_provider",
        ],
    )
    module = SimpleNamespace(
        chop_engine_schema_version=lambda: 1,
        validate_axe_config=lambda _request: [],
    )

    assert not validator._validate_axe_chop_guard_providers(
        module, schema_path=schema_path
    )


def test_validate_axe_chop_guard_providers_degrades_gracefully_without_raising(
    tmp_path: Path,
) -> None:
    validator = load_validate_sase_core_rs()
    schema_path = _write_guard_schema(tmp_path)
    module = SimpleNamespace()

    assert not validator._validate_axe_chop_guard_providers(
        module, schema_path=schema_path
    )
