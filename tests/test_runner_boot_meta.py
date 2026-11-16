"""Boot-meta keys survive directive extraction and runner-side re-stamps."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.axe import run_agent_markers, run_agent_runner_bootstrap
from sase.axe.runner_boot_meta import RUNNER_BOOT_META_KEYS
from sase.env_contracts import SASE_LAUNCH_SCRATCH_KEY_ENV
from tests._agent_names_extract_fixtures import run_extract


def test_preserved_agent_metadata_keeps_runner_boot_keys(tmp_path: Path) -> None:
    from sase.axe.run_agent_directive_metadata import preserved_agent_metadata

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "runner_capabilities": ["hijack"],
                "code_identity": {"schema_version": 1, "roots": []},
                "booted_at": "2026-11-06T12:00:00+00:00",
                "launch_scratch_key": "agent-ws3-fixture",
                "prompt_origin": "human",
                "prompt_source_surface": "cli",
            }
        ),
        encoding="utf-8",
    )

    preserved = preserved_agent_metadata(str(artifacts_dir))

    for key in RUNNER_BOOT_META_KEYS:
        assert key in preserved, key
    assert preserved["runner_capabilities"] == ["hijack"]
    assert preserved["launch_scratch_key"] == "agent-ws3-fixture"


def test_bootstrap_then_directive_extract_keeps_runner_boot_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(SASE_LAUNCH_SCRATCH_KEY_ENV, "agent-ws3-invariant")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    run_agent_runner_bootstrap._write_bootstrap_agent_meta(
        str(artifacts), output_path="out.log", refreshed=False
    )
    boot = json.loads((artifacts / "agent_meta.json").read_text(encoding="utf-8"))
    for key in RUNNER_BOOT_META_KEYS:
        if key == "launch_scratch_key":
            assert boot[key] == "agent-ws3-invariant"
        else:
            assert key in boot, key

    extracted = run_extract(
        tmp_path,
        prompt="%model:fakey/fakey-large@high\nContinue the assigned work.",
        cl_name="ace(run)-invariant",
        workspace_num=3,
    )
    meta = extracted["meta"]
    for key in RUNNER_BOOT_META_KEYS:
        assert key in meta, key
        assert meta[key] == boot[key]


def test_marker_write_restamps_hijack_capability_for_this_process(
    tmp_path: Path,
) -> None:
    meta: dict[str, Any] = {"pid": os.getpid()}
    with patch.object(run_agent_markers, "write_agent_meta_atomic"):
        run_agent_markers.write_agent_meta(str(tmp_path), meta)
    assert meta["runner_capabilities"] == ["hijack"]


def test_marker_write_does_not_restamp_hijack_capability_for_another_process(
    tmp_path: Path,
) -> None:
    meta: dict[str, Any] = {"pid": os.getpid() + 1}
    with patch.object(run_agent_markers, "write_agent_meta_atomic"):
        run_agent_markers.write_agent_meta(str(tmp_path), meta)
    assert "runner_capabilities" not in meta
