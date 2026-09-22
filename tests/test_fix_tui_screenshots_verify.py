"""Per-golden determinism agreement tests for screenshot maintenance."""

from __future__ import annotations

import json
from pathlib import Path

from tests._fix_tui_screenshots_helpers import (
    ACE_NODE,
    PAGER_NODE,
    AttemptScript,
    FakeRunner,
    ScriptedCapture,
    commit_all,
    init_repo,
    make_png,
    silent_hooks,
    write_golden,
)
from tests.ace.tui.visual._visual_maintenance import EXIT_SUCCESS, main


OTHER_NODE = "tests/ace/tui/visual/test_a.py::test_other"


def _manifest(repo: Path) -> dict:
    paths = sorted(
        (repo / ".pytest_cache/sase-visual/runs").glob("*/manifest.json"),
        key=lambda path: path.stat().st_mtime_ns,
    )
    assert paths
    return json.loads(paths[-1].read_text(encoding="utf-8"))


def _setup(
    repo: Path,
    *,
    baseline: bytes,
    candidate: bytes,
    pager_candidate: bytes | None = None,
    verify_attempts: list[AttemptScript] | None = None,
    verify_captures: list[ScriptedCapture] | None = None,
) -> tuple[Path, FakeRunner]:
    init_repo(repo)
    target = write_golden(repo, "ace", "shot.png", baseline)
    pager_baseline = baseline
    pager_bytes = pager_candidate if pager_candidate is not None else baseline
    write_golden(repo, "pager", "keep.png", pager_baseline)
    commit_all(repo)
    runner = FakeRunner(
        captures=[
            ScriptedCapture(ACE_NODE, "shot", "ace", candidate),
            ScriptedCapture(PAGER_NODE, "keep", "pager", pager_bytes),
        ],
        repo_root=repo,
        verify_attempts=list(verify_attempts or []),
        verify_captures=verify_captures,
    )
    return target, runner


def test_first_verify_agrees_applies(tmp_path: Path) -> None:
    red = make_png(1, 1, (255, 0, 0, 255))
    blue = make_png(1, 1, (0, 0, 255, 255))
    target, runner = _setup(tmp_path, baseline=red, candidate=blue)
    assert (
        main([], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_SUCCESS
    )
    assert target.read_bytes() == blue
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "applied"
    assert manifest["skipped"] == []
    labels = [attempt["label"] for attempt in manifest["attempts"]]
    assert labels == ["capture", "verify"]
    verify_calls = [call for call in runner.calls if "verify" in str(call["run_id"])]
    assert len(verify_calls) == 1
    assert verify_calls[0]["workers"] is None


def test_flicker_then_agrees_with_capture(tmp_path: Path) -> None:
    red = make_png(1, 1, (255, 0, 0, 255))
    blue = make_png(1, 1, (0, 0, 255, 255))
    green = make_png(1, 1, (0, 255, 0, 255))
    target, runner = _setup(
        tmp_path,
        baseline=red,
        candidate=blue,
        verify_attempts=[
            AttemptScript(exit_code=0, pngs={ACE_NODE: green}),
            AttemptScript(exit_code=0, pngs={ACE_NODE: blue}),
        ],
    )
    assert (
        main([], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_SUCCESS
    )
    assert target.read_bytes() == blue
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "applied"
    assert manifest["skipped"] == []
    labels = [attempt["label"] for attempt in manifest["attempts"]]
    assert labels == ["capture", "verify", "verify-2"]


def test_agreed_bytes_from_verify_are_applied(tmp_path: Path) -> None:
    red = make_png(1, 1, (255, 0, 0, 255))
    blue = make_png(1, 1, (0, 0, 255, 255))
    green = make_png(1, 1, (0, 255, 0, 255))
    target, runner = _setup(
        tmp_path,
        baseline=red,
        candidate=blue,
        verify_attempts=[
            AttemptScript(exit_code=0, pngs={ACE_NODE: green}),
            AttemptScript(exit_code=0, pngs={ACE_NODE: green}),
        ],
    )
    assert (
        main([], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_SUCCESS
    )
    assert target.read_bytes() == green
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "applied"
    assert manifest["skipped"] == []


def test_agreement_with_baseline_is_unchanged(tmp_path: Path) -> None:
    red = make_png(1, 1, (255, 0, 0, 255))
    blue = make_png(1, 1, (0, 0, 255, 255))
    target, runner = _setup(
        tmp_path,
        baseline=red,
        candidate=blue,
        verify_attempts=[
            AttemptScript(exit_code=0, pngs={ACE_NODE: red}),
            AttemptScript(exit_code=0, pngs={ACE_NODE: red}),
        ],
    )
    mtime = target.stat().st_mtime_ns
    assert (
        main([], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_SUCCESS
    )
    assert target.read_bytes() == red
    assert target.stat().st_mtime_ns == mtime
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "clean"
    assert manifest["skipped"] == []
    assert not any(
        item["kind"] in {"created", "updated"} for item in manifest["changes"]
    )


def test_never_agrees_skips_unstable_and_applies_rest(tmp_path: Path) -> None:
    red = make_png(1, 1, (255, 0, 0, 255))
    blue = make_png(1, 1, (0, 0, 255, 255))
    green = make_png(1, 1, (0, 255, 0, 255))
    yellow = make_png(1, 1, (255, 255, 0, 255))
    cyan = make_png(1, 1, (0, 255, 255, 255))
    init_repo(tmp_path)
    ace = write_golden(tmp_path, "ace", "shot.png", red)
    pager = write_golden(tmp_path, "pager", "keep.png", red)
    commit_all(tmp_path)
    runner = FakeRunner(
        captures=[
            ScriptedCapture(ACE_NODE, "shot", "ace", blue),
            ScriptedCapture(PAGER_NODE, "keep", "pager", blue),
        ],
        repo_root=tmp_path,
        verify_attempts=[
            AttemptScript(exit_code=0, pngs={ACE_NODE: green}),
            AttemptScript(exit_code=0, pngs={ACE_NODE: yellow}),
            AttemptScript(exit_code=0, pngs={ACE_NODE: cyan}),
        ],
    )
    assert (
        main([], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_SUCCESS
    )
    assert ace.read_bytes() == red
    assert pager.read_bytes() == blue
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "partial"
    unstable = [item for item in manifest["skipped"] if item["reason"] == "unstable"]
    assert len(unstable) == 1
    assert unstable[0]["path"] is not None and unstable[0]["path"].endswith("shot.png")
    assert unstable[0]["node_id"] == ACE_NODE
    assert len(unstable[0]["evidence"]) >= 2
    assert any(
        item["kind"] == "updated" and item["path"].endswith("keep.png")
        for item in manifest["changes"]
    )
    labels = [attempt["label"] for attempt in manifest["attempts"]]
    assert labels == ["capture", "verify", "verify-2", "verify-3"]


def test_verify_node_fails_then_passes_serially(tmp_path: Path) -> None:
    red = make_png(1, 1, (255, 0, 0, 255))
    blue = make_png(1, 1, (0, 0, 255, 255))
    target, runner = _setup(
        tmp_path,
        baseline=red,
        candidate=blue,
        verify_attempts=[
            AttemptScript(exit_code=1, failed=(ACE_NODE,)),
            AttemptScript(exit_code=0),
        ],
    )
    assert (
        main([], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_SUCCESS
    )
    assert target.read_bytes() == blue
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "applied"
    assert manifest["skipped"] == []
    labels = [attempt["label"] for attempt in manifest["attempts"]]
    assert labels == ["capture", "verify", "verify-2"]


def test_verify_session_only_exit_is_ignored(tmp_path: Path) -> None:
    red = make_png(1, 1, (255, 0, 0, 255))
    blue = make_png(1, 1, (0, 0, 255, 255))
    target, runner = _setup(
        tmp_path,
        baseline=red,
        candidate=blue,
        verify_attempts=[AttemptScript(exit_code=1)],
    )
    assert (
        main([], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_SUCCESS
    )
    assert target.read_bytes() == blue
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "applied"
    assert manifest["skipped"] == []
    verify_attempts = [
        attempt for attempt in manifest["attempts"] if "verify" in attempt["label"]
    ]
    assert verify_attempts and verify_attempts[0]["child_exit_code"] == 1


def test_owner_mismatch_is_skipped(tmp_path: Path) -> None:
    red = make_png(1, 1, (255, 0, 0, 255))
    blue = make_png(1, 1, (0, 0, 255, 255))
    target, runner = _setup(
        tmp_path,
        baseline=red,
        candidate=blue,
        verify_captures=[
            ScriptedCapture(OTHER_NODE, "shot", "ace", blue),
            ScriptedCapture(PAGER_NODE, "keep", "pager", red),
        ],
    )
    assert (
        main([], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_SUCCESS
    )
    assert target.read_bytes() == red
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "partial"
    mismatched = [
        item for item in manifest["skipped"] if item["reason"] == "owner_mismatch"
    ]
    assert len(mismatched) == 1
    assert mismatched[0]["node_id"] == ACE_NODE


def test_reverification_uses_serial_workers(tmp_path: Path) -> None:
    red = make_png(1, 1, (255, 0, 0, 255))
    blue = make_png(1, 1, (0, 0, 255, 255))
    green = make_png(1, 1, (0, 255, 0, 255))
    target, runner = _setup(
        tmp_path,
        baseline=red,
        candidate=blue,
        verify_attempts=[
            AttemptScript(exit_code=0, pngs={ACE_NODE: green}),
            AttemptScript(exit_code=0, pngs={ACE_NODE: blue}),
        ],
    )
    assert (
        main([], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_SUCCESS
    )
    assert target.read_bytes() == blue
    verify_calls = [call for call in runner.calls if "verify" in str(call["run_id"])]
    assert len(verify_calls) == 2
    assert verify_calls[0]["workers"] is None
    assert verify_calls[1]["workers"] == 1
    assert tuple(verify_calls[1]["pytest_args"]) == (ACE_NODE,)
