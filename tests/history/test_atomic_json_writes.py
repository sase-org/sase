"""Atomic replacement regressions for flat history JSON stores."""

import json
import multiprocessing
import threading
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sase.history import vcs_macro_mru
from sase.history.command import CommandEntry, _save_command_history
from sase.history.hook import HookHistoryEntry, _save_hook_history
from sase.history.vcs_macro_mru import _save_vcs_macro_mru


def _assert_atomic_replacements(
    path: Path,
    write_state: Callable[[int], object],
    expected: set[str],
) -> None:
    write_state(0)
    invalid: list[str] = []
    finished = threading.Event()

    def read_while_writing() -> None:
        while not finished.is_set():
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                if json.dumps(value, sort_keys=True) not in expected:
                    invalid.append(f"unexpected state: {value!r}")
            except (OSError, json.JSONDecodeError) as exc:
                invalid.append(f"unreadable target: {exc}")
            time.sleep(0)

    reader = threading.Thread(target=read_while_writing)
    reader.start()
    try:
        for index in range(1, 13):
            write_state(index % 2)
    finally:
        finished.set()
        reader.join()

    assert invalid == []


def _normalized(value: object) -> str:
    return json.dumps(value, sort_keys=True)


def _record_mru_entries(path: str, worker_id: int) -> None:
    import sase.project_aliases as project_aliases
    from sase.history import vcs_macro_mru as mru

    mru._MRU_FILE = Path(path)
    project_aliases.canonicalize_project_aliases_in_prompt = lambda value: value
    mru._mru_build_state = lambda _projects_dir: SimpleNamespace(
        records=None, alias_map={}, detect_cache={}
    )
    mru._is_default_vcs_macro_prefix = lambda _prefix: False
    mru._is_stale_known_project_prefix = lambda *_args, **_kwargs: False
    mru._resolvable_vcs_ref_index = lambda **_kwargs: None
    mru._vcs_prefix_provider_mismatched = lambda *_args, **_kwargs: False

    for entry_id in range(8):
        mru.record_vcs_macro_usage(f"#git:worker-{worker_id}-{entry_id}")


def test_history_saves_never_truncate_the_target(tmp_path: Path) -> None:
    mru_file = tmp_path / "vcs_macro_mru.json"
    mru_states = [{"entries": ["#git:first"]}, {"entries": ["#git:second"]}]
    with patch("sase.history.vcs_macro_mru._MRU_FILE", mru_file):
        _assert_atomic_replacements(
            mru_file,
            lambda index: _save_vcs_macro_mru(
                ["#git:first", "#git:second"][index : index + 1]
            ),
            {_normalized(state) for state in mru_states},
        )

    hook_file = tmp_path / "hook_history.json"
    hook_states = [
        {"hooks": [{"command": command, "timestamp": "t", "last_used": "t"}]}
        for command in ("first", "second")
    ]
    with patch("sase.history.hook._HOOK_HISTORY_FILE", hook_file):
        _assert_atomic_replacements(
            hook_file,
            lambda index: _save_hook_history(
                [
                    HookHistoryEntry(
                        command=("first", "second")[index],
                        timestamp="t",
                        last_used="t",
                    )
                ]
            ),
            {_normalized(state) for state in hook_states},
        )

    command_file = tmp_path / "command_history.json"
    command_states = [
        {
            "commands": [
                {
                    "command": command,
                    "project": "project",
                    "cl_name": None,
                    "timestamp": "t",
                    "last_used": "t",
                }
            ]
        }
        for command in ("first", "second")
    ]
    with patch("sase.history.command._COMMAND_HISTORY_FILE", command_file):
        _assert_atomic_replacements(
            command_file,
            lambda index: _save_command_history(
                [
                    CommandEntry(
                        command=("first", "second")[index],
                        project="project",
                        cl_name=None,
                        timestamp="t",
                        last_used="t",
                    )
                ]
            ),
            {_normalized(state) for state in command_states},
        )


def test_concurrent_mru_updates_keep_every_entry(tmp_path: Path) -> None:
    mru_file = tmp_path / "vcs_macro_mru.json"
    with patch.object(vcs_macro_mru, "_MRU_FILE", mru_file):
        _save_vcs_macro_mru(["#git:seed"])
        context = multiprocessing.get_context("spawn")
        workers = [
            context.Process(target=_record_mru_entries, args=(str(mru_file), worker_id))
            for worker_id in range(4)
        ]
        for worker in workers:
            worker.start()

        invalid: list[str] = []
        while any(worker.is_alive() for worker in workers):
            try:
                json.loads(mru_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                invalid.append(f"unreadable target: {exc}")
            time.sleep(0)

        for worker in workers:
            worker.join()
            assert worker.exitcode == 0

        entries = vcs_macro_mru._load_vcs_macro_mru()
        expected = {
            f"#git:worker-{worker_id}-{entry_id}"
            for worker_id in range(4)
            for entry_id in range(8)
        }
        assert set(entries) == expected | {"#git:seed"}
        assert invalid == []
