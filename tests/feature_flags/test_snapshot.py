"""Process feature-flag snapshot tests."""

from __future__ import annotations

import importlib
import logging
import os
from collections.abc import Mapping
from typing import Any

import pytest

from sase.config.core import ConfigLayer
from sase.feature_flags import FeatureFlagError
from sase.feature_flags.env import SASE_FEATURE_FLAGS_ENV
from sase.feature_flags.models import FeatureFlagDiagnostic
from sase.feature_flags.resolver import FeatureFlagLayerInput
from sase.feature_flags import snapshot as snapshot_mod

from ._helpers import definitions, demo_flag, layer


def _install_snapshot_inputs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    defs: Mapping[str, Any],
    layers: tuple[FeatureFlagLayerInput, ...] = (),
    diagnostics: tuple[FeatureFlagDiagnostic, ...] = (),
) -> None:
    monkeypatch.setattr(snapshot_mod, "feature_flag_definitions", lambda: defs)
    monkeypatch.setattr(
        snapshot_mod,
        "_project_layer_inputs",
        lambda: (layers, diagnostics),
    )
    snapshot_mod.reset_process_feature_flags()


def test_current_flags_is_lazy_once_and_snapshot_mapping_is_immutable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_snapshot_inputs(
        monkeypatch,
        defs=definitions(demo_flag(default=True)),
    )

    first = snapshot_mod.current_flags()
    second = snapshot_mod.current_flags()

    assert first is second
    assert first.enabled("demo_flag") is True
    with pytest.raises(TypeError):
        first.decisions["demo_flag"] = first.decision("demo_flag")
    with pytest.raises(FeatureFlagError):
        first.enabled("missing_flag")


def test_override_flags_nests_and_restores_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_snapshot_inputs(
        monkeypatch,
        defs=definitions(demo_flag(default=False)),
    )
    original = snapshot_mod.current_flags()

    with pytest.raises(RuntimeError):
        with snapshot_mod.override_flags(demo_flag=True) as outer:
            assert outer.enabled("demo_flag") is True
            assert snapshot_mod.current_flags() is outer
            with snapshot_mod.override_flags(demo_flag=False) as inner:
                assert inner.enabled("demo_flag") is False
            assert snapshot_mod.current_flags() is outer
            raise RuntimeError("restore")

    assert snapshot_mod.current_flags() is original
    assert original.enabled("demo_flag") is False


def test_install_process_feature_flags_is_idempotent_and_logs_once(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _install_snapshot_inputs(
        monkeypatch,
        defs=definitions(demo_flag(default=False)),
        layers=(layer("user", {"demo_flag": True}),),
    )
    monkeypatch.delenv(SASE_FEATURE_FLAGS_ENV, raising=False)
    caplog.set_level(logging.INFO, logger="sase.feature_flags.snapshot")

    first = snapshot_mod.install_process_feature_flags()
    second = snapshot_mod.install_process_feature_flags()

    assert first is second
    assert os.environ[SASE_FEATURE_FLAGS_ENV] == '{"demo_flag":true}'
    messages = [record.getMessage() for record in caplog.records]
    assert (
        messages.count("feature flags resolved; non-default: demo_flag=True (user)")
        == 1
    )


def test_layer_projection_warns_when_feature_flags_is_not_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        snapshot_mod,
        "feature_flag_definitions",
        lambda: definitions(demo_flag()),
    )
    monkeypatch.setattr(
        "sase.config.core.load_config_layers",
        lambda: [
            ConfigLayer(
                name="user",
                path="/home/u/.config/sase/sase.yml",
                exists=True,
                list_strategy="replace",
                data={"feature_flags": ["not", "a", "mapping"]},
            )
        ],
    )
    snapshot_mod.reset_process_feature_flags()

    resolved = snapshot_mod.current_flags()

    assert resolved.enabled("demo_flag") is False
    assert [diagnostic.code for diagnostic in resolved.diagnostics] == ["not_a_mapping"]
    assert resolved.diagnostics[0].source == "user"


def test_importing_feature_flags_and_sase_performs_no_resolution() -> None:
    snapshot_mod.reset_process_feature_flags()

    importlib.import_module("sase.feature_flags")
    importlib.import_module("sase")

    assert snapshot_mod._snapshot is None
