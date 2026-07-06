from __future__ import annotations

from sase.doctor import checks_tools


def test_optional_tools_include_mpv_for_video_artifact_playback(monkeypatch) -> None:
    monkeypatch.setattr(checks_tools.shutil, "which", lambda _tool: None)

    check = checks_tools._check_optional_tools()

    rows = {row["id"]: row for row in check.data["tools"]}
    assert rows["mpv"]["commands"] == ("mpv",)
    assert rows["mpv"]["feature"] == "terminal video artifact playback"
    assert "terminal video artifact playback: install mpv" in check.details
