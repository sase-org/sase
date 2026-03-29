"""Tests for sase_commit_stop_hook dedup marker semantics."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.scripts.sase_commit_stop_hook import main


def _env_base(tmp_path: Path) -> dict[str, str]:
    """Return a minimal env dict pointing at tmp_path as both project and tmpdir."""
    return {
        "CLAUDE_PROJECT_DIR": str(tmp_path),
        "SASE_TMPDIR": str(tmp_path),
        "SASE_AGENT_TIMESTAMP": "test_session",
        "SASE_COMMIT_METHOD": "create_commit",
    }


def _marker(tmp_path: Path) -> Path:
    return tmp_path / "sase_commit_hook_done_test_session"


def _log_events(log_file: Path) -> list[str]:
    if not log_file.exists():
        return []
    return [json.loads(line)["event"] for line in log_file.read_text().splitlines()]


# ── changes exist + marker exists → still blocks ──────────────────────


def test_blocks_when_changes_exist_and_marker_present(
    tmp_path: Path, monkeypatch: object
) -> None:
    """When uncommitted changes exist and a stale marker is present, the hook
    must still block (not silently skip)."""
    env = _env_base(tmp_path)
    marker = _marker(tmp_path)
    marker.touch()

    monkeypatch.setattr("os.environ", env)  # type: ignore[attr-defined]

    with (
        patch(
            "sase.scripts.sase_commit_stop_hook._get_changed_files",
            return_value=(True, ["src/foo.py"]),
        ),
        patch(
            "sase.scripts.sase_commit_stop_hook._resolve_commit_skill",
            return_value="/sase_git_commit",
        ),
        patch(
            "sase.scripts.sase_commit_stop_hook.LOG_FILE", str(tmp_path / "log.jsonl")
        ),
        patch("sase.scripts.sase_commit_stop_hook._log_hook_run"),
    ):
        rc = main()

    assert rc == 2  # Claude runtime → exit 2 means block
    events = _log_events(tmp_path / "log.jsonl")
    assert "stale_marker_ignored" in events
    assert "block_emitted" in events


# ── no changes → writes marker and exits clean ────────────────────────


def test_no_changes_writes_marker_and_exits_clean(
    tmp_path: Path, monkeypatch: object
) -> None:
    """When no uncommitted changes exist, the hook should write the dedup
    marker and exit cleanly."""
    env = _env_base(tmp_path)
    marker = _marker(tmp_path)
    assert not marker.exists()

    monkeypatch.setattr("os.environ", env)  # type: ignore[attr-defined]

    with (
        patch(
            "sase.scripts.sase_commit_stop_hook._get_changed_files",
            return_value=(False, []),
        ),
        patch(
            "sase.scripts.sase_commit_stop_hook.LOG_FILE", str(tmp_path / "log.jsonl")
        ),
        patch("sase.scripts.sase_commit_stop_hook._log_hook_run"),
    ):
        rc = main()

    assert rc == 0
    assert marker.exists()
    events = _log_events(tmp_path / "log.jsonl")
    assert "block_emitted" not in events


# ── changes exist without prior marker → blocks, no marker written ────


def test_blocks_when_changes_exist_no_prior_marker(
    tmp_path: Path, monkeypatch: object
) -> None:
    """First-time block: changes exist, no prior marker. Hook should block
    and NOT write a marker."""
    env = _env_base(tmp_path)
    marker = _marker(tmp_path)

    monkeypatch.setattr("os.environ", env)  # type: ignore[attr-defined]

    with (
        patch(
            "sase.scripts.sase_commit_stop_hook._get_changed_files",
            return_value=(True, ["src/bar.py"]),
        ),
        patch(
            "sase.scripts.sase_commit_stop_hook._resolve_commit_skill",
            return_value="/sase_git_commit",
        ),
        patch(
            "sase.scripts.sase_commit_stop_hook.LOG_FILE", str(tmp_path / "log.jsonl")
        ),
        patch("sase.scripts.sase_commit_stop_hook._log_hook_run"),
    ):
        rc = main()

    assert rc == 2
    assert not marker.exists()
    events = _log_events(tmp_path / "log.jsonl")
    assert "block_emitted" in events
    assert "stale_marker_ignored" not in events


# ── Gemini stop_hook_active still short-circuits ──────────────────────


def test_gemini_stop_hook_active_still_deduplicates(
    tmp_path: Path, monkeypatch: object
) -> None:
    """Gemini's stop_hook_active stdin guard should still short-circuit,
    regardless of marker state or changes."""
    env = {
        **_env_base(tmp_path),
        "GEMINI_PROJECT_DIR": str(tmp_path),
    }
    # Remove Claude-specific key so Gemini runtime is detected
    env.pop("CLAUDE_PROJECT_DIR", None)

    monkeypatch.setattr("os.environ", env)  # type: ignore[attr-defined]

    with (
        patch(
            "sase.scripts.sase_commit_stop_hook._read_gemini_stdin",
            return_value={"stop_hook_active": True},
        ),
        patch(
            "sase.scripts.sase_commit_stop_hook.LOG_FILE", str(tmp_path / "log.jsonl")
        ),
        patch("sase.scripts.sase_commit_stop_hook._log_hook_run"),
    ):
        rc = main()

    assert rc == 0
    events = _log_events(tmp_path / "log.jsonl")
    assert "gemini_dedup_skip" in events
