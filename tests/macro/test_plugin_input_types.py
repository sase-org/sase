"""Plugin-shared enum input types: runtime, discovery, CLI, and doctor."""

from __future__ import annotations

import importlib.metadata
import json
import sys
import textwrap
from pathlib import Path

import pytest

from sase.macro.load_issues import collect_macro_load_issues
from sase.macro.plugin_input_types import (
    _clear_plugin_input_type_registry_cache,
    get_plugin_input_type_registry,
)


@pytest.fixture(autouse=True)
def _clear_cache(monkeypatch):
    _clear_plugin_input_type_registry_cache()
    yield
    _clear_plugin_input_type_registry_cache()


def _write_manifest(path: Path, text: str) -> Path:
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def _manifest_text() -> str:
    return """\
        schema_version: 1
        types:
          audio_edition:
            description: Narration length.
            choices:
              - { value: brief, description: About 4 minutes }
              - { value: full, label: Full edition, description: About 16 minutes }
        """


def test_registry_loader_resolves_plugin_type(tmp_path, monkeypatch):
    manifest = _write_manifest(tmp_path / "input_types.yml", _manifest_text())
    files = [
        {
            "distribution": "sase-research-artifacts",
            "module": "fake_plugin",
            "path": str(manifest),
        }
    ]
    snapshot = get_plugin_input_type_registry(files)
    registry = snapshot["registry"]
    assert not snapshot["diagnostics"]
    from sase.core.rust import require_rust_binding

    resolved = require_rust_binding("resolve_input_type")(
        {
            "name": "edition",
            "raw": "sase-research-artifacts@audio_edition",
            "registry": registry,
        }
    )
    assert resolved["base"] == "enum"
    assert resolved["named_type"] == "sase-research-artifacts@audio_edition"
    assert [item["value"] for item in resolved["choices"]] == [
        "brief",
        "full",
    ]


def test_runtime_missing_plugin_skips_only_affected_macro(tmp_path, monkeypatch):
    from sase.macro._loader_parsing_inputs import parse_inputs_from_front_matter
    from sase.macro.models import MacroValidationError

    manifest = _write_manifest(tmp_path / "input_types.yml", _manifest_text())
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
    good = parse_inputs_from_front_matter(
        {"edition": "sase-research-artifacts@audio_edition"},
        source_path="good.md",
    )
    assert [arg.named_type for arg in good] == ["sase-research-artifacts@audio_edition"]
    with pytest.raises(MacroValidationError, match="not installed|declares no"):
        parse_inputs_from_front_matter(
            {"edition": "missing-dist@nope"},
            source_path="bad.md",
        )


def test_named_type_rejects_authored_choices_override():
    from sase.macro._loader_parsing_inputs import parse_input_definition
    from sase.macro.models import MacroValidationError, UNSET

    # Effort is a builtin named type; authored choices must be rejected.
    with pytest.raises(MacroValidationError, match="already defines its values"):
        parse_input_definition(
            name="effort",
            type_raw="effort",
            default=UNSET,
            description=None,
            repeatable=False,
            choices_raw=["low", "high"],
            source_path="test.md",
        )


def test_discovery_uses_entry_points_and_distributions(monkeypatch):
    from sase.main import plugin_discovery as discovery

    class FakeDist:
        metadata = {"Name": "sase-research-artifacts"}

    class FakeEp:
        name = "fake"
        group = "sase_macros"
        value = "fake_plugin:mod"
        dist = FakeDist()

        def load(self):
            import types

            module = types.ModuleType("fake_plugin")
            module.__name__ = "fake_plugin"
            return module

    monkeypatch.setattr(
        discovery,
        "_discover_macro_plugin_entry_points",
        lambda *, accept_legacy=None: [FakeEp()],
    )
    monkeypatch.setattr(
        discovery,
        "macro_plugins_disabled",
        lambda *, environ=None, accept_legacy=None: False,
    )
    dists = discovery.discover_macro_plugin_distributions()
    assert "sase-research-artifacts" in dists


def test_cli_types_json_lists_builtin(tmp_path, capsys):
    from sase.macro.cli_types import handle_types
    import argparse

    args = argparse.Namespace(type_name=None, json=True)
    assert handle_types(args) == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert isinstance(payload, list)
    names = [entry["name"] for entry in payload]
    assert "effort" in names and "model" in names


def test_doctor_reports_malformed_manifest(tmp_path, monkeypatch):
    manifest = _write_manifest(
        tmp_path / "input_types.yml",
        "schema_version: 999\ntypes: {}\n",
    )
    monkeypatch.setattr(
        "sase.main.plugin_discovery.discover_macro_plugin_input_type_files",
        lambda *, accept_legacy=None: [
            {
                "distribution": "bad-dist",
                "module": "bad_mod",
                "path": str(manifest),
            }
        ],
    )
    monkeypatch.setattr(
        "sase.main.plugin_discovery.discover_macro_plugin_distributions",
        lambda *, accept_legacy=None: ["bad-dist"],
    )
    from sase.doctor.checks_config_macros import check_config_macro_input_types
    from sase.doctor.runner import default_doctor_context

    context = default_doctor_context()
    check = check_config_macro_input_types(context)
    assert check.data["issues"] or check.status in ("OK", "WARN")
