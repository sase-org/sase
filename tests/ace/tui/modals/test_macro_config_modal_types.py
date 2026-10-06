"""Validation for config macro input types via the Rust catalog."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from sase.ace.tui.modals.macro_config_modal import validate_config_input_type
from sase.macro.plugin_input_types import _clear_plugin_input_type_registry_cache


@pytest.fixture(autouse=True)
def _clear_cache():
    _clear_plugin_input_type_registry_cache()
    yield
    _clear_plugin_input_type_registry_cache()


def test_named_builtin_types_accepted() -> None:
    assert validate_config_input_type("level", "effort") is None
    assert validate_config_input_type("claude_model", "model") is None


def test_inline_enum_rejected() -> None:
    error = validate_config_input_type("status", "enum")
    assert error is not None
    assert "choices" in error.casefold()


def test_typo_suggests_enum() -> None:
    error = validate_config_input_type("status", "enmu")
    assert error is not None
    assert "enum" in error


def test_plugin_type_resolves_with_fixture_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = tmp_path / "input_types.yml"
    manifest.write_text(
        textwrap.dedent(
            """\
            schema_version: 1
            types:
              audio_edition:
                description: Narration length.
                choices:
                  - { value: brief }
                  - { value: full }
            """
        ),
        encoding="utf-8",
    )
    files = [
        {
            "distribution": "sase-research-artifacts",
            "module": "fake_plugin",
            "path": str(manifest),
        }
    ]
    monkeypatch.setattr(
        "sase.main.plugin_discovery.discover_macro_plugin_input_type_files",
        lambda *, accept_legacy=None: list(files),
    )
    monkeypatch.setattr(
        "sase.main.plugin_discovery.discover_macro_plugin_distributions",
        lambda *, accept_legacy=None: ["sase-research-artifacts"],
    )
    _clear_plugin_input_type_registry_cache()
    assert (
        validate_config_input_type("edition", "sase-research-artifacts@audio_edition")
        is None
    )
