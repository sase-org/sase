from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.agent_meta import write_agent_meta_atomic
from sase.axe import run_agent_markers, runner_artifacts


def test_agent_meta_atomic_replace_keeps_old_complete_snapshot_until_publish(
    tmp_path: Path,
) -> None:
    meta_path = tmp_path / "agent_meta.json"
    old_meta = {
        "name": "agent-a",
        "run_started_at": "2026-08-08T12:00:00+00:00",
    }
    new_meta = {
        "name": "agent-a",
        "run_started_at": "2026-08-08T12:01:00+00:00",
        "workspace_dir": "/tmp/workspace",
    }
    meta_path.write_text(json.dumps(old_meta, indent=2), encoding="utf-8")

    original_replace = os.replace
    replace_reached = threading.Event()
    release_replace = threading.Event()
    index_reads: list[dict[str, object]] = []
    errors: list[BaseException] = []

    def _blocked_replace(
        src: str | os.PathLike[str], dst: str | os.PathLike[str]
    ) -> None:
        replace_reached.set()
        assert json.loads(meta_path.read_text(encoding="utf-8")) == old_meta
        assert release_replace.wait(timeout=2.0)
        original_replace(src, dst)

    def _record_index_update(_artifacts_dir: str) -> None:
        index_reads.append(json.loads(meta_path.read_text(encoding="utf-8")))

    def _writer() -> None:
        try:
            write_agent_meta_atomic(tmp_path, new_meta)
        except BaseException as exc:  # pragma: no cover - surfaced by assertion below
            errors.append(exc)

    with (
        patch("sase.axe.agent_meta.os.replace", side_effect=_blocked_replace),
        patch(
            "sase.core.agent_artifact_index_lifecycle."
            "update_agent_artifact_index_for_marker_mutation",
            side_effect=_record_index_update,
        ),
    ):
        thread = threading.Thread(target=_writer)
        thread.start()
        assert replace_reached.wait(timeout=2.0)
        assert json.loads(meta_path.read_text(encoding="utf-8")) == old_meta
        assert index_reads == []
        release_replace.set()
        thread.join(timeout=2.0)

    assert not thread.is_alive()
    assert errors == []
    assert json.loads(meta_path.read_text(encoding="utf-8")) == new_meta
    assert index_reads == [new_meta]


def test_agent_meta_atomic_cleans_temp_and_propagates_replace_error(
    tmp_path: Path,
) -> None:
    with (
        patch("sase.axe.agent_meta.os.replace", side_effect=OSError("replace failed")),
        patch(
            "sase.core.agent_artifact_index_lifecycle."
            "update_agent_artifact_index_for_marker_mutation"
        ) as update_index,
    ):
        with pytest.raises(OSError, match="replace failed"):
            write_agent_meta_atomic(tmp_path, {"name": "agent-a"})

    assert list(tmp_path.glob(".agent_meta.json.*.tmp")) == []
    assert not (tmp_path / "agent_meta.json").exists()
    update_index.assert_not_called()


def test_generic_and_specialized_agent_meta_writers_use_atomic_publication(
    tmp_path: Path,
) -> None:
    generic_dir = tmp_path / "generic"
    specialized_dir = tmp_path / "specialized"
    generic_dir.mkdir()
    specialized_dir.mkdir()

    calls: list[str] = []
    with (
        patch(
            "sase.axe.run_agent_markers."
            "update_agent_artifact_index_for_marker_mutation",
            side_effect=lambda path: calls.append(path),
        ),
        patch(
            "sase.core.agent_artifact_index_lifecycle."
            "update_agent_artifact_index_for_marker_mutation",
            side_effect=lambda path: calls.append(path),
        ),
    ):
        meta = {"name": "agent-a", "tag": "review"}
        run_agent_markers.write_agent_meta(str(generic_dir), meta)
        with patch("sase.axe.runner_artifacts.os.getpid", return_value=123):
            runner_artifacts.write_agent_meta(
                str(specialized_dir),
                model="model-a",
                llm_provider="provider-a",
                vcs_provider="Git",
                tribe="review",
            )

    generic_meta = json.loads(
        (generic_dir / "agent_meta.json").read_text(encoding="utf-8")
    )
    specialized_meta = json.loads(
        (specialized_dir / "agent_meta.json").read_text(encoding="utf-8")
    )
    assert generic_meta["tribe"] == "review"
    assert "tag" not in generic_meta
    assert meta == generic_meta
    assert specialized_meta == {
        "pid": 123,
        "model": "model-a",
        "llm_provider": "provider-a",
        "vcs_provider": "Git",
        "tribe": "review",
    }
    assert calls == [str(generic_dir), str(specialized_dir)]
