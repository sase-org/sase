"""Draft-attach qualification transport integration tests.

Split from ``tests.test_qualification_transport_integration``; the original
module re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import yaml

from tests._qualification_transport_integration_helpers import (
    RELEASE_WORKFLOW,
    fake_gh_fixture,  # noqa: F401 (registers the fake_gh fixture)
)

__all__ = [
    "test_draft_attach_uses_canonical_asset_bytes",
]


def _attach_block() -> str:
    workflow = yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["qualify"]["steps"]
    attach = next(
        step
        for step in steps
        if step.get("name") == "Attach the qualification observation to the draft"
    )
    return attach["run"]


def _run_attach(
    block: str, tmp_path: Path, asset: str, tag: str
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, ASSET=asset, TAG=tag)
    return subprocess.run(
        ["bash", "-c", block],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        cwd=tmp_path,
        env=env,
    )


def test_draft_attach_uses_canonical_asset_bytes(fake_gh: Path, tmp_path: Path) -> None:
    block = _attach_block()
    assert 'gh release upload "${TAG}" "$ASSET"' in block
    asset = "candidate-gen1-qualification-run700-attempt1.json"
    body = json.dumps({"asset": asset, "verdict": "pass"})
    (tmp_path / asset).write_text(body, encoding="utf-8")
    tag = "v0.18.0"
    first = _run_attach(block, tmp_path, asset, tag)
    assert first.returncode == 0, first.stderr
    remote = fake_gh / "remote" / tag / asset
    assert remote.is_file()
    assert remote.read_text(encoding="utf-8") == body
    calls = (fake_gh / "calls.log").read_text(encoding="utf-8")
    assert f"release upload {tag} {asset}" in calls
    # Re-appending identical bytes is a no-op.
    uploads_before = calls.count(f"release upload {tag} {asset}")
    second = _run_attach(block, tmp_path, asset, tag)
    assert second.returncode == 0, second.stderr
    assert "already attached; skipping upload" in second.stdout
    calls = (fake_gh / "calls.log").read_text(encoding="utf-8")
    assert calls.count(f"release upload {tag} {asset}") == uploads_before
    # Conflicting bytes refuse without replacement.
    remote.write_text(json.dumps({"asset": asset, "verdict": "red"}), encoding="utf-8")
    third = _run_attach(block, tmp_path, asset, tag)
    assert third.returncode != 0
    assert "conflicting qualification observation" in third.stdout
    assert remote.read_text(encoding="utf-8") != body
