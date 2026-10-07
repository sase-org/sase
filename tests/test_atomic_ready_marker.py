"""Atomic ready.json publication and defensive runner-side reading.

Covers the ``atomic-ready`` phase: ``publish_ready_marker`` publishes via a
temp file plus no-clobber link (first writer wins, no temp files left
behind, skipped when the waiter is gone), and ``read_ready_result`` treats
a torn, empty, or non-dict marker as not ready.
"""

import json
from pathlib import Path

import sase.scripts._chop_wait_checks_run as wait_checks_module
from sase.axe.run_agent_wait_deps import read_ready_result
from sase.axe.run_agent_wait_markers import publish_ready_marker

from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import make_waiting_agent, run_wait_checks


def _write(path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_read_ready_result_valid_marker_releases(tmp_path: Path) -> None:
    ready = _write(tmp_path / "ready.json", json.dumps({"resolved_deps": ["wf"]}))
    assert read_ready_result(ready)


def test_read_ready_result_torn_marker_parks(tmp_path: Path) -> None:
    ready = _write(tmp_path / "ready.json", '{"resolved_deps": ["w')
    assert not read_ready_result(ready)
    # A torn marker is left alone so a later poll can see the finished file.
    assert (tmp_path / "ready.json").exists()


def test_read_ready_result_empty_file_parks(tmp_path: Path) -> None:
    ready = _write(tmp_path / "ready.json", "")
    assert not read_ready_result(ready)


def test_read_ready_result_non_dict_marker_parks(tmp_path: Path) -> None:
    ready = _write(tmp_path / "ready.json", json.dumps(["wf"]))
    assert not read_ready_result(ready)


def test_read_ready_result_missing_file_parks(tmp_path: Path) -> None:
    assert not read_ready_result(str(tmp_path / "ready.json"))


def test_read_ready_result_legacy_cancelled_unlinks_and_parks(
    tmp_path: Path,
) -> None:
    ready_path = tmp_path / "ready.json"
    _write(ready_path, json.dumps({"cancelled": True}))
    assert not read_ready_result(str(ready_path))
    assert not ready_path.exists()


def test_publish_ready_marker_first_writer_wins(tmp_path: Path) -> None:
    (tmp_path / "waiting.json").write_text(json.dumps({"waiting_for": ["wf"]}))
    assert publish_ready_marker(str(tmp_path), {"resolved_deps": ["wf"]}) is True
    assert publish_ready_marker(str(tmp_path), {"resolved_deps": ["other"]}) is False
    assert json.loads((tmp_path / "ready.json").read_text()) == {
        "resolved_deps": ["wf"]
    }
    assert [p for p in tmp_path.iterdir() if p.name.startswith(".ready.json.")] == []


def test_publish_ready_marker_skips_when_waiter_gone(tmp_path: Path) -> None:
    assert publish_ready_marker(str(tmp_path), {"resolved_deps": ["wf"]}) is False
    assert not (tmp_path / "ready.json").exists()
    assert [p for p in tmp_path.iterdir() if p.name.startswith(".ready.json.")] == []


def test_wait_checks_late_ready_marker_counts_already_ready(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "late-dep", suffix="waiter")
    make_agent(
        tmp_path,
        "proj",
        "20260506020202",
        "late-dep",
        done=True,
        outcome="completed",
    )

    real_publish = wait_checks_module.publish_ready_marker
    sentinel = {"resolved_deps": ["concurrent-winner"]}

    def _racing_publish(artifacts_dir: str, payload: dict) -> bool:
        # Simulate a ready.json published between the scan and our publish.
        (Path(artifacts_dir) / "ready.json").write_text(json.dumps(sentinel))
        return real_publish(artifacts_dir, payload)

    monkeypatch.setattr(wait_checks_module, "publish_ready_marker", _racing_publish)
    run_wait_checks(tmp_path, monkeypatch)

    out = capsys.readouterr().out
    assert "ready_written=0" in out
    assert "already_ready=1" in out
    assert json.loads((waiter_dir / "ready.json").read_text()) == sentinel
    assert [p for p in waiter_dir.iterdir() if p.name.startswith(".ready.json.")] == []
