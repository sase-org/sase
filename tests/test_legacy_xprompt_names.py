"""Legacy-input tests for the xprompt-to-macro durable rename.

Every fixture below is a realistic pre-rename artifact named
``*legacy_xprompt*`` (or written under a pre-rename filename): readers must
accept it, and writers must never produce it. Later codemods must skip this
file's fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.legacy_xprompt_names import (
    LEGACY_MACROS_FILENAME,
    LEGACY_RAW_XPROMPT_FILENAME,
    LEGACY_XPROMPT_SAVE_STATE_FILENAME,
    LEGACY_XPROMPT_SAVE_STATE_KEY,
    LEGACY_XPROMPT_SET_SHA256_KEY,
    LEGACY_VCS_XPROMPT_MRU_FILENAME,
    MACROS_FILENAME,
    MACRO_SAVE_STATE_FILENAME,
    MACRO_SAVE_STATE_KEY,
    MACRO_SET_SHA256_KEY,
    PROMPT_PROC_FIELD,
    PROMPT_PROC_ORIGIN,
    RAW_PROMPT_FILENAME,
    SUBMITTED_PROMPT_FILENAME,
    VCS_MACRO_MRU_FILENAME,
    artifact_candidates,
    legacy_macros_step_filename,
    macros_step_filename,
    macro_set_sha256,
    prompt_proc_origin_matches,
    prompt_proc_payload,
    read_raw_prompt_text,
    read_json_new_first,
    resolve_raw_prompt_path,
)
from tests.conftest import redirect_sase_home


def _write_legacy_xprompt_agent_dir(path: Path) -> None:
    """Write a pre-rename agent directory: only legacy artifact names."""
    from sase.legacy_xprompt_names import LEGACY_SUBMITTED_XPROMPT_FILENAME

    path.mkdir(parents=True)
    (path / LEGACY_RAW_XPROMPT_FILENAME).write_text("#plan do it", encoding="utf-8")
    (path / LEGACY_SUBMITTED_XPROMPT_FILENAME).write_text(
        "#plan do it", encoding="utf-8"
    )
    (path / LEGACY_MACROS_FILENAME).write_text(
        json.dumps([{"name": "plan", "kind": "workflow", "tags": []}]),
        encoding="utf-8",
    )
    (path / legacy_macros_step_filename("main")).write_text("[]", encoding="utf-8")


def test_raw_prompt_reader_prefers_canonical_but_accepts_legacy(
    tmp_path: Path,
) -> None:
    legacy_dir = tmp_path / "legacy_xprompt_agent"
    _write_legacy_xprompt_agent_dir(legacy_dir)

    assert read_raw_prompt_text(legacy_dir) == "#plan do it"
    assert resolve_raw_prompt_path(legacy_dir) == (
        legacy_dir / LEGACY_RAW_XPROMPT_FILENAME
    )

    (legacy_dir / RAW_PROMPT_FILENAME).write_text("#new prompt", encoding="utf-8")
    assert read_raw_prompt_text(legacy_dir) == "#new prompt"
    assert resolve_raw_prompt_path(legacy_dir) == legacy_dir / RAW_PROMPT_FILENAME


def test_macros_step_filenames() -> None:
    assert macros_step_filename("main") == "macros_main.json"
    assert legacy_macros_step_filename("main") == "xprompts_main.json"
    assert MACROS_FILENAME == "macros.json"
    assert RAW_PROMPT_FILENAME == "raw_prompt.md"
    assert SUBMITTED_PROMPT_FILENAME == "submitted_prompt.md"


def test_artifact_candidates_order_canonical_first(tmp_path: Path) -> None:
    first, second = artifact_candidates(
        tmp_path, RAW_PROMPT_FILENAME, LEGACY_RAW_XPROMPT_FILENAME
    )
    assert first == tmp_path / RAW_PROMPT_FILENAME
    assert second == tmp_path / LEGACY_RAW_XPROMPT_FILENAME


def test_read_json_new_first_prefers_canonical(tmp_path: Path) -> None:
    canonical = tmp_path / VCS_MACRO_MRU_FILENAME
    legacy = tmp_path / LEGACY_VCS_XPROMPT_MRU_FILENAME
    canonical.write_text(json.dumps({"entries": ["#gh:new"]}), encoding="utf-8")
    legacy.write_text(json.dumps({"entries": ["#gh:old"]}), encoding="utf-8")

    payload, source = read_json_new_first(canonical, legacy)

    assert payload == {"entries": ["#gh:new"]}
    assert source == canonical


def test_read_json_new_first_falls_back_to_legacy(tmp_path: Path) -> None:
    canonical = tmp_path / VCS_MACRO_MRU_FILENAME
    legacy = tmp_path / LEGACY_VCS_XPROMPT_MRU_FILENAME
    legacy.write_text(json.dumps({"entries": ["#gh:old"]}), encoding="utf-8")

    payload, source = read_json_new_first(canonical, legacy)

    assert payload == {"entries": ["#gh:old"]}
    assert source == legacy
    assert read_json_new_first(canonical, tmp_path / "missing.json") == (None, None)


def test_mru_record_migrates_legacy_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from sase.history import vcs_xprompt_mru
    from sase.history.vcs_xprompt_mru import (
        _load_vcs_xprompt_mru,
        record_vcs_xprompt_usage,
    )

    home = redirect_sase_home(monkeypatch, tmp_path / ".sase")
    legacy = home / LEGACY_VCS_XPROMPT_MRU_FILENAME
    legacy.write_text(json.dumps({"entries": ["#gh:old"]}), encoding="utf-8")
    monkeypatch.setattr(vcs_xprompt_mru, "_MRU_FILE", None)

    assert _load_vcs_xprompt_mru() == ["#gh:old"]
    record_vcs_xprompt_usage("#gh:new")

    assert _load_vcs_xprompt_mru() == ["#gh:new", "#gh:old"]
    assert not legacy.exists()
    assert (home / VCS_MACRO_MRU_FILENAME).is_file()


def test_save_state_reads_legacy_file_and_key(tmp_path: Path) -> None:
    from sase.xprompt.save_state import (
        load_last_used_locations,
        save_last_used_location,
    )

    legacy = tmp_path / LEGACY_XPROMPT_SAVE_STATE_FILENAME
    legacy.write_text(
        json.dumps({LEGACY_XPROMPT_SAVE_STATE_KEY: "/tmp/xprompts"}), encoding="utf-8"
    )
    with patch("sase.xprompt.save_state._SAVE_STATE_FILE", tmp_path / "state.json"):
        # The hook's sibling legacy file stands in for a real legacy home file.
        assert legacy.is_file()
        assert load_last_used_locations() == {"xprompt": "/tmp/xprompts"}

        assert save_last_used_location("xprompt", "/tmp/macros")
        assert load_last_used_locations() == {"xprompt": "/tmp/macros"}
        assert not legacy.exists()


def test_save_state_writes_canonical_file_and_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from sase.xprompt import save_state
    from sase.xprompt.save_state import (
        load_last_used_locations,
        save_last_used_location,
    )

    home = redirect_sase_home(monkeypatch, tmp_path / ".sase")
    legacy = home / LEGACY_XPROMPT_SAVE_STATE_FILENAME
    legacy.write_text(
        json.dumps({LEGACY_XPROMPT_SAVE_STATE_KEY: "/tmp/xprompts"}), encoding="utf-8"
    )
    monkeypatch.setattr(save_state, "_SAVE_STATE_FILE", None)

    assert load_last_used_locations() == {"xprompt": "/tmp/xprompts"}
    assert save_last_used_location("xprompt", "/tmp/macros")

    canonical = home / MACRO_SAVE_STATE_FILENAME
    payload = json.loads(canonical.read_text(encoding="utf-8"))
    assert payload == {MACRO_SAVE_STATE_KEY: "/tmp/macros"}
    assert MACRO_SAVE_STATE_KEY == "macro"
    assert not legacy.exists()


def test_manifest_hash_accepts_legacy_key() -> None:
    assert macro_set_sha256({LEGACY_XPROMPT_SET_SHA256_KEY: "old-hash"}) == "old-hash"
    assert macro_set_sha256({MACRO_SET_SHA256_KEY: "new-hash"}) == "new-hash"
    assert (
        macro_set_sha256(
            {MACRO_SET_SHA256_KEY: "new-hash", LEGACY_XPROMPT_SET_SHA256_KEY: "old"}
        )
        == "new-hash"
    )
    assert macro_set_sha256({}) is None
    assert MACRO_SET_SHA256_KEY == "macro_set_sha256"


def test_legacy_manifest_satisfies_provenance_guard(tmp_path: Path) -> None:
    from sase.main._init_skills_manifest import _read_manifest

    manifest = tmp_path / ".sase-skills-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "deployed_at": "2026-07-28T12:00:00Z",
                "managed_files": [],
                "source_commit": "abc123",
                LEGACY_XPROMPT_SET_SHA256_KEY: "old-hash",
            }
        ),
        encoding="utf-8",
    )

    recorded, error = _read_manifest(
        manifest, chezmoi_home=tmp_path, home_root=tmp_path
    )

    assert error is None
    assert recorded is not None
    assert recorded.xprompt_set_sha256 == "old-hash"


def test_proc_legacy_row_reads_and_writes_canonical() -> None:
    from sase.procs.models.proc import Proc

    legacy_row = {
        "schema_version": 2,
        "proc_id": "proc-1",
        "label": "label",
        "kind": "command",
        "status": "success",
        "command": ["echo"],
        "argv": ["echo"],
        "cwd": "/tmp",
        "origin": "xprompt-proc",
        "created_at": "t",
        "log_path": "/tmp/log",
        "xprompt_proc": {"proc_name": "inner"},
    }

    assert prompt_proc_origin_matches("xprompt-proc")
    assert prompt_proc_origin_matches("prompt-proc")
    assert not prompt_proc_origin_matches("named-proc")
    assert PROMPT_PROC_ORIGIN == "prompt-proc"
    assert prompt_proc_payload(legacy_row) == {"proc_name": "inner"}
    assert prompt_proc_payload({PROMPT_PROC_FIELD: {"a": 1}}) == {"a": 1}
    assert prompt_proc_payload({}) is None

    proc = Proc.from_dict(legacy_row)
    assert proc.xprompt_proc is not None
    assert proc.xprompt_proc["proc_name"] == "inner"

    payload = proc.to_dict()
    assert PROMPT_PROC_FIELD == "prompt_proc"
    assert "xprompt_proc" not in payload
    assert payload["prompt_proc"]["proc_name"] == "inner"

    assert Proc.from_dict(payload).xprompt_proc == proc.xprompt_proc


def test_disabled_regions_accept_both_spellings() -> None:
    from sase.xprompt._disabled_regions import (
        protect_disabled_regions,
        strip_disabled_region_markers,
        strip_disabled_regions,
    )

    for directive in ("xprompts_enabled", "macros_enabled"):
        text = f"%{directive}:false\nsecret\n%{directive}:true\nvisible\n"
        regions: list[str] = []
        protected = protect_disabled_regions(text, regions)
        assert "secret" not in protected
        assert "visible" in protected
        assert strip_disabled_regions(text) == "visible\n"
        assert directive not in strip_disabled_region_markers(text)


def test_revival_lookup_prefers_canonical(tmp_path: Path) -> None:
    from sase.core.revival_inputs import (
        capture_revival_inputs,
        revival_input_file,
    )

    live = tmp_path / "proj" / "artifacts" / "ace-run" / "20260710010000"
    live.mkdir(parents=True)
    (live / LEGACY_RAW_XPROMPT_FILENAME).write_text("legacy prompt", encoding="utf-8")
    (live / RAW_PROMPT_FILENAME).write_text("new prompt", encoding="utf-8")

    assert capture_revival_inputs(live) is not None
    found = revival_input_file(live, LEGACY_RAW_XPROMPT_FILENAME)
    assert found is not None
    assert found.read_text(encoding="utf-8") == "new prompt"


def test_prompt_panel_reader_accepts_legacy_step_files(tmp_path: Path) -> None:
    from sase.ace.tui.widgets.prompt_panel._helpers import load_xprompts_used

    class _Agent:
        def __init__(self, artifacts_dir: str | None, step_name: str | None) -> None:
            self._dir = artifacts_dir
            self.step_name = step_name

        def get_artifacts_dir(self) -> str | None:
            return self._dir

    legacy_dir = tmp_path / "legacy_xprompt_agent"
    _write_legacy_xprompt_agent_dir(legacy_dir)

    assert load_xprompts_used(_Agent(str(legacy_dir), None)) == [
        {"name": "plan", "kind": "workflow", "tags": []}
    ]
    assert load_xprompts_used(_Agent(str(legacy_dir), "main")) is None
    (legacy_dir / macros_step_filename("main")).write_text(
        json.dumps([{"name": "step"}]), encoding="utf-8"
    )
    assert load_xprompts_used(_Agent(str(legacy_dir), "main")) == [{"name": "step"}]
    assert load_xprompts_used(_Agent(None, None)) is None


def test_swarm_env_prefers_macro_spelling() -> None:
    from sase.xprompt.used_xprompts import (
        SASE_LAUNCH_SWARM_MACROS,
        SASE_LAUNCH_SWARM_XPROMPTS,
        decode_launch_swarm_xprompts,
        launch_swarm_env_entries,
        pop_launch_swarm_env,
    )

    entries = launch_swarm_env_entries(["a"])
    assert entries[SASE_LAUNCH_SWARM_MACROS] == '["a"]'
    assert entries[SASE_LAUNCH_SWARM_XPROMPTS] == '["a"]'

    assert decode_launch_swarm_xprompts(
        {SASE_LAUNCH_SWARM_MACROS: '["m"]', SASE_LAUNCH_SWARM_XPROMPTS: '["x"]'}
    ) == ["m"]
    assert decode_launch_swarm_xprompts({SASE_LAUNCH_SWARM_XPROMPTS: '["x"]'}) == ["x"]
    assert decode_launch_swarm_xprompts({}) is None

    env = {SASE_LAUNCH_SWARM_MACROS: "1", SASE_LAUNCH_SWARM_XPROMPTS: "2"}
    pop_launch_swarm_env(env)
    assert env == {}
