"""Tests for the instruction-manifest thin adapter."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from sase.core import instruction_manifest as im
from sase.core.instruction_manifest import (
    INSTRUCTION_MANIFEST_WIRE_SCHEMA_VERSION,
    _InstructionManifestError,
    normalize_instruction_manifest,
    wire_schema_version,
)
from sase.core.rust import require_rust_binding

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "instruction_manifest_v1.json"
)


def _load_fixture() -> dict:
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


def test_schema_version_matches_binding() -> None:
    assert INSTRUCTION_MANIFEST_WIRE_SCHEMA_VERSION == 1
    assert wire_schema_version() == INSTRUCTION_MANIFEST_WIRE_SCHEMA_VERSION
    binding = require_rust_binding("instruction_manifest_wire_schema_version")
    assert int(binding()) == INSTRUCTION_MANIFEST_WIRE_SCHEMA_VERSION


def test_golden_fixture_normalizes_unchanged() -> None:
    fixture = _load_fixture()
    assert normalize_instruction_manifest(copy.deepcopy(fixture)) == fixture


def test_closed_vocab_tuples_cover_wire_values() -> None:
    assert set(im.INSTRUCTION_MANIFEST_LAYERS) == {
        "frame",
        "package",
        "plugin",
        "home",
        "project",
        "launch",
    }
    assert set(im.INSTRUCTION_MANIFEST_SECTION_STATUSES) == {
        "included",
        "excluded",
    }
    assert set(im.INSTRUCTION_MANIFEST_SECTION_REASONS) == {
        "superseded_input",
        "shadowed",
        "overlay",
        "mode",
        "no_directive",
        "empty",
    }
    assert set(im.INSTRUCTION_MANIFEST_LIFECYCLES) == {
        "neutral",
        "root",
        "helper",
    }
    assert set(im.INSTRUCTION_MANIFEST_SOURCE_SCOPES) == {
        "package",
        "plugin",
        "home",
        "project",
        "launch",
    }
    assert set(im.INSTRUCTION_MANIFEST_SOURCE_KINDS) == {
        "package_template",
        "helper_template",
        "provider_directive",
        "memory_note",
        "memory_web",
        "memory_strands",
        "config",
        "generated",
        "legacy_fallback",
    }
    assert set(im.INSTRUCTION_MANIFEST_DELIVERY_STATUSES) == {
        "preview",
        "shadow",
        "explicit",
        "inherits_native",
        "inherits_root",
        "none",
    }
    assert set(im.INSTRUCTION_MANIFEST_CACHE_STATUSES) == {
        "hit",
        "miss",
        "bypass",
    }
    assert set(im.INSTRUCTION_MANIFEST_OBSERVATION_STATUSES) == {
        "unobserved",
        "observed",
        "partial",
        "unavailable",
    }
    assert set(im.INSTRUCTION_MANIFEST_ACTORS) == {
        "sase_root",
        "native_helper",
        "interactive",
    }
    assert set(im.INSTRUCTION_MANIFEST_MODES) == {
        "runtime",
        "interactive",
        "export",
    }
    assert set(im.INSTRUCTION_MANIFEST_PURPOSES) == {
        "ordinary",
        "declaration_recovery",
        "conflict_repair",
    }


def test_rejects_unknown_actor() -> None:
    manifest = _load_fixture()
    manifest["facts"]["actor"] = "codx"
    with pytest.raises(_InstructionManifestError):
        normalize_instruction_manifest(manifest)


def test_rejects_provider_specific_on_non_provider_id() -> None:
    manifest = _load_fixture()
    manifest["sections"][1]["provider_specific"] = True
    with pytest.raises(_InstructionManifestError, match="provider_specific"):
        normalize_instruction_manifest(manifest)


def test_common_digest_filled_when_null() -> None:
    manifest = _load_fixture()
    manifest["bundle"]["common_digest"] = None
    normalized = normalize_instruction_manifest(manifest)
    assert (
        normalized["bundle"]["common_digest"]
        == _load_fixture()["bundle"]["common_digest"]
    )


def test_common_digest_rejected_when_wrong() -> None:
    manifest = _load_fixture()
    manifest["bundle"]["common_digest"] = "0" * 64
    with pytest.raises(_InstructionManifestError, match="common_digest"):
        normalize_instruction_manifest(manifest)


def test_common_digest_unchanged_by_provider_only_change() -> None:
    manifest = _load_fixture()
    before = manifest["bundle"]["common_digest"]
    manifest["sections"][3]["sha256"] = "e" * 64
    normalized = normalize_instruction_manifest(manifest)
    assert normalized["bundle"]["common_digest"] == before
