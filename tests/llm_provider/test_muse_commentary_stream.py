"""Stream-level tests for Muse live-reply commentary."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from sase.llm_provider._subprocess_muse import stream_and_parse_muse_json_output

from ._muse_commentary_helpers import (
    build_fake_muse_exec_script,
    commentary_record,
    install_muse_session_log,
    muse_delta,
    muse_task_lifecycle,
    muse_terminal,
    run_muse_stream,
)
from ._muse_provider_helpers import _read_timestamps

_SESSION_ID = "66b7ac36-396c-49f1-a3ef-58d4e1a43008"
_COMMENTARY_1 = "Approved — implementing your docs theme plan now."
_COMMENTARY_2 = "Next I will run the tests."
_FINAL = "Done. Phase complete."


def _session_body() -> str:
    return (
        commentary_record(
            session_id=_SESSION_ID,
            text=_COMMENTARY_1,
            message_id="msg-1",
            sequence=1,
        )
        + commentary_record(
            session_id=_SESSION_ID,
            text=_COMMENTARY_2,
            message_id="msg-2",
            sequence=2,
        )
        + commentary_record(
            session_id=_SESSION_ID,
            text=_FINAL,
            message_id="msg-final",
            sequence=3,
            phase=None,
        )
    )


def test_commentary_chunks_land_before_the_final_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    install_muse_session_log(tmp_path, _SESSION_ID, _session_body())

    stdout = muse_task_lifecycle() + muse_delta(_FINAL) + muse_terminal(_FINAL)
    content, stderr, return_code, _usage = run_muse_stream(
        stdout, session_id=_SESSION_ID
    )

    assert return_code == 0
    assert stderr == ""
    assert content == _FINAL
    live_reply = (artifacts / "live_reply.md").read_text(encoding="utf-8")
    assert live_reply == f"{_COMMENTARY_1}\n\n{_COMMENTARY_2}\n\n{_FINAL}"
    offsets = [entry["byte_offset"] for entry in _read_timestamps(artifacts)]
    first = _COMMENTARY_1.encode()
    second = _COMMENTARY_2.encode()
    assert offsets == [0, len(first), len(first) + 2 + len(second)]


def test_without_session_id_output_matches_stdout_deltas_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    install_muse_session_log(tmp_path, _SESSION_ID, _session_body())

    stdout = muse_delta(_FINAL) + muse_terminal(_FINAL)
    content, _, return_code, _ = run_muse_stream(stdout)

    assert return_code == 0
    assert content == _FINAL
    live_reply = (artifacts / "live_reply.md").read_text(encoding="utf-8")
    assert live_reply == _FINAL
    assert len(_read_timestamps(artifacts)) == 1


def test_terminal_fallback_writes_text_once_when_no_deltas_streamed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))

    content, _, return_code, _ = run_muse_stream(muse_terminal(_FINAL))

    assert return_code == 0
    assert content == _FINAL
    live_reply = (artifacts / "live_reply.md").read_text(encoding="utf-8")
    assert live_reply == _FINAL
    assert len(_read_timestamps(artifacts)) == 1


def test_terminal_fallback_does_not_duplicate_streamed_deltas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))

    content, _, _, _ = run_muse_stream(muse_delta(_FINAL) + muse_terminal(_FINAL))

    assert content == _FINAL
    live_reply = (artifacts / "live_reply.md").read_text(encoding="utf-8")
    assert live_reply == _FINAL
    assert live_reply.count(_FINAL) == 1


def test_commentary_is_visible_before_the_handshake_releases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    xdg = tmp_path / "xdg"
    xdg.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg))

    ready = tmp_path / "ready"
    release = tmp_path / "release"
    script = build_fake_muse_exec_script(
        session_id=_SESSION_ID,
        commentaries=(_COMMENTARY_1, _COMMENTARY_2),
        final_answer=_FINAL,
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(ready), str(release)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    result: list[tuple[str, str, int, dict[str, int]]] = []
    failures: list[BaseException] = []

    def run() -> None:
        try:
            result.append(
                stream_and_parse_muse_json_output(
                    process, suppress_output=True, session_id=_SESSION_ID
                )
            )
        except BaseException as exc:  # surface reader-thread failures
            failures.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.01)  # sase-test-wait: poll fake muse ready marker
    assert ready.exists(), "fake muse did not signal ready"
    assert process.poll() is None

    live = artifacts / "live_reply.md"
    metadata_path = artifacts / "run_metadata.json"
    while time.monotonic() < deadline:
        if live.is_file() and metadata_path.is_file():
            body = live.read_text(encoding="utf-8")
            if _COMMENTARY_1 in body and _COMMENTARY_2 in body:
                break
        time.sleep(0.02)  # sase-test-wait: poll live_reply until commentary lands
    else:
        body = live.read_text(encoding="utf-8") if live.is_file() else ""
        raise AssertionError(f"commentary did not appear before handshake: {body!r}")

    body = live.read_text(encoding="utf-8")
    assert _FINAL not in body
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["muse_session_id"] == _SESSION_ID
    assert metadata["runtime"] == "muse"
    assert process.poll() is None

    release.write_text("go", encoding="utf-8")
    thread.join(timeout=5)
    assert not failures
    assert result
    content, stderr, return_code, _usage = result[0]
    assert return_code == 0
    assert stderr == ""
    assert content == _FINAL
    final_live = live.read_text(encoding="utf-8")
    assert final_live.index(_COMMENTARY_1) < final_live.index(_FINAL)
    assert final_live.count(_FINAL) == 1
    assert process.wait(timeout=1) == 0


def test_stream_json_lines_calls_on_tick_while_stdout_is_quiet() -> None:
    from sase.llm_provider._subprocess_stream import stream_json_lines

    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(0.45)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    ticks_while_alive = 0

    def on_tick() -> None:
        nonlocal ticks_while_alive
        if process.poll() is None:
            ticks_while_alive += 1

    _stderr, return_code = stream_json_lines(
        process, lambda _line: None, True, on_tick=on_tick
    )
    assert return_code == 0
    assert ticks_while_alive >= 2
