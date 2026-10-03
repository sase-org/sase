"""Tests for Agents-tab MEMORY lane version chips and the launch row."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sase.ace.tui.widgets.prompt_panel._agent_memory_versions import (
    MemoryLaunchRow,
    MemoryVersionChip,
    _aggregate_chip,
    _chip_for_result,
    resolve_event_chips,
    resolve_launch_row,
    scope_for_event,
)

BLOB_A = "a" * 40
BLOB_B = "b" * 40


def _result(
    ordinal: int, *, newer_count: int = 0, now_matches: bool = False
) -> dict[str, Any]:
    return {
        "ordinal": ordinal,
        "version": {"ordinal": ordinal},
        "newest": ordinal + newer_count,
        "newest_version": {"ordinal": ordinal + newer_count},
        "newer_count": newer_count,
        "now_matches": now_matches,
    }


class _Scope:
    def __init__(self, key: str = "project:sase", repo_root: str = "/tmp/repo"):
        self.scope_key = key
        self.repo_root = repo_root


class _Service:
    def __init__(self, scope: _Scope | None = None):
        self._scope = scope or _Scope()

    def project_scope(self, root: Any) -> _Scope:
        return self._scope

    def home_scope(self) -> None:
        return None


class _History:
    def __init__(
        self,
        results: dict[str, Any],
        *,
        service: _Service | None = None,
    ):
        self._results = results
        self.service = service or _Service()
        self.calls: list[tuple[str, str]] = []

    def version_for_blob(self, scope: Any, selector: str, oid: str) -> Any:
        self.calls.append((selector, oid))
        outcome = self._results[oid]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _event(**override: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": "read-1",
        "project": "",
        "cwd": "/tmp/repo",
        "selectors": ("gotchas.md",),
        "canonical_path": "gotchas.md",
        "blob_oid": BLOB_A,
        "included_blob_oids": (),
    }
    base.update(override)
    return SimpleNamespace(**base)


def test_now_chip_is_dim_equiv() -> None:
    chip = _chip_for_result(_result(25, now_matches=True))
    assert chip is not None
    assert chip.text == "≡ now"
    assert chip.style == "dim"


def test_past_chip_names_version_and_newer_count() -> None:
    chip = _chip_for_result(_result(24, newer_count=1))
    assert chip is not None
    assert chip.text == "v24 ⟲ 1 newer"


def test_newest_dirty_chip_names_version_without_newer() -> None:
    chip = _chip_for_result(_result(25, newer_count=0, now_matches=False))
    assert chip is not None
    assert chip.text == "v25"


def test_uncommitted_chip_is_amber() -> None:
    chip = _chip_for_result("uncommitted")
    assert chip is not None
    assert chip.text == "◌ uncommitted at read"


def test_missing_result_renders_no_chip() -> None:
    assert _chip_for_result(None) is None


def test_aggregate_chip_all_current() -> None:
    chip = _aggregate_chip([_result(3, now_matches=True), _result(5, now_matches=True)])
    assert chip is not None
    assert chip.text == "≡ now"


def test_aggregate_chip_counts_changed() -> None:
    chip = _aggregate_chip(
        [_result(3, now_matches=True), _result(4, newer_count=1), "uncommitted"]
    )
    assert chip is not None
    assert chip.text == "⟲ 2 of 3 changed"


def test_aggregate_chip_empty_renders_nothing() -> None:
    assert _aggregate_chip([]) is None
    assert _aggregate_chip([None]) is None


def test_single_read_resolves_chip_and_pin() -> None:
    history = _History({BLOB_A: _result(24, newer_count=1)})
    chip, pins = resolve_event_chips(_event(), history=history, service=_Service())
    assert chip is not None
    assert chip.text == "v24 ⟲ 1 newer"
    assert pins == [("gotchas.md", 24)]
    assert history.calls == [("gotchas.md", BLOB_A)]


def test_uncommitted_blob_yields_amber_chip_and_no_pin() -> None:
    history = _History({BLOB_A: LookupError("no version")})
    chip, pins = resolve_event_chips(_event(), history=history, service=_Service())
    assert chip is not None
    assert chip.text == "◌ uncommitted at read"
    assert pins == [("gotchas.md", None)]


def test_batch_read_yields_aggregate_chip() -> None:
    event = _event(
        selectors=("gotchas.md", "dispatch.md"),
        blob_oid=None,
        included_blob_oids=(("gotchas.md", BLOB_A), ("dispatch.md", BLOB_B)),
    )
    history = _History(
        {
            BLOB_A: _result(25, now_matches=True),
            BLOB_B: _result(12, newer_count=2),
        }
    )
    chip, pins = resolve_event_chips(event, history=history, service=_Service())
    assert chip is not None
    assert chip.text == "⟲ 1 of 2 changed"
    assert pins == [("gotchas.md", 25), ("dispatch.md", 12)]


def test_read_without_blob_yields_no_chip() -> None:
    history = _History({})
    chip, pins = resolve_event_chips(
        _event(blob_oid=None), history=history, service=_Service()
    )
    assert chip is None
    # The target still pins to None so batch rows never collapse to a
    # single-target pager pin.
    assert pins == [("gotchas.md", None)]
    assert history.calls == []


def test_unresolvable_scope_omits_chips() -> None:
    class _FailingService:
        def project_scope(self, root: Any) -> Any:
            raise ValueError("no such project")

    history = _History({BLOB_A: _result(1, now_matches=True)})
    chip, pins = resolve_event_chips(
        _event(), history=history, service=_FailingService()
    )
    assert chip is None
    assert pins == []
    assert history.calls == []


def test_only_visible_rows_resolve() -> None:
    from sase.ace.tui.widgets.prompt_panel._agent_memory_reads import (
        MAX_VISIBLE_READS,
    )

    assert MAX_VISIBLE_READS == 5


def _agent(
    tmp_path: Path,
    *,
    workspace_dir: str | None = None,
    meta: dict[str, Any] | None = None,
) -> SimpleNamespace:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    if meta is not None:
        (artifacts / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return SimpleNamespace(
        workspace_dir=workspace_dir if workspace_dir is not None else str(tmp_path),
        get_artifacts_dir=lambda: str(artifacts),
    )


def test_launch_row_current_version(tmp_path: Path) -> None:
    history = _History({"oid": _result(258, now_matches=True)}, service=_Service())
    agent = _agent(
        tmp_path,
        workspace_dir=str(tmp_path),
        meta={
            "instruction_snapshot": [
                {
                    "path": str(tmp_path / "AGENTS.md"),
                    "repo": "project",
                    "blob_oid": "oid",
                    "tracked": True,
                }
            ]
        },
    )
    # Point the workspace at the fake scope's repo through the service.
    row = resolve_launch_row(agent, history=history, service=history.service)
    assert row is not None
    assert row.display == "AGENTS.md"
    assert row.chip is not None
    assert row.chip.text == "≡ now"
    assert row.ordinal == 258


def test_launch_row_past_version_counts_since_launch(tmp_path: Path) -> None:
    history = _History({"oid": _result(258, newer_count=2)}, service=_Service())
    agent = _agent(
        tmp_path,
        workspace_dir=str(tmp_path),
        meta={
            "instruction_snapshot": [
                {
                    "path": str(tmp_path / "AGENTS.md"),
                    "repo": "project",
                    "blob_oid": "oid",
                    "tracked": True,
                }
            ]
        },
    )
    row = resolve_launch_row(agent, history=history, service=history.service)
    assert row is not None
    assert row.chip is not None
    assert row.chip.text == "v258 ⟲ 2 newer since launch"


def test_launch_row_not_in_git(tmp_path: Path, monkeypatch) -> None:
    import sase.ace.tui.widgets.prompt_panel._agent_memory_versions as versions

    history = _History({BLOB_A: LookupError("gone")}, service=_Service())
    monkeypatch.setattr(versions, "_snapshot_bytes_present", lambda blob: True)
    agent = _agent(
        tmp_path,
        workspace_dir=str(tmp_path),
        meta={
            "instruction_snapshot": [
                {
                    "path": str(tmp_path / "AGENTS.md"),
                    "repo": "project",
                    "blob_oid": BLOB_A,
                    "tracked": False,
                }
            ]
        },
    )
    row = resolve_launch_row(agent, history=history, service=history.service)
    assert row is not None
    assert row.chip is not None
    assert row.chip.text == "◌ as launched · not in git"
    assert row.ordinal is None
    assert not row.unavailable


def test_launch_row_snapshot_gone_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    import sase.ace.tui.widgets.prompt_panel._agent_memory_versions as versions

    history = _History({BLOB_A: LookupError("gone")}, service=_Service())
    monkeypatch.setattr(versions, "_snapshot_bytes_present", lambda blob: False)
    agent = _agent(
        tmp_path,
        workspace_dir=str(tmp_path),
        meta={
            "instruction_snapshot": [
                {
                    "path": str(tmp_path / "AGENTS.md"),
                    "repo": "project",
                    "blob_oid": BLOB_A,
                    "tracked": False,
                }
            ]
        },
    )
    row = resolve_launch_row(agent, history=history, service=history.service)
    assert row is not None
    assert row.chip is not None
    assert row.chip.text == "snapshot unavailable"
    assert row.unavailable


def test_launch_row_missing_for_agent_without_evidence(tmp_path: Path) -> None:
    history = _History({}, service=_Service())
    agent = _agent(tmp_path, workspace_dir=str(tmp_path), meta=None)
    assert resolve_launch_row(agent, history=history, service=history.service) is None


def test_launch_row_missing_for_agent_without_workspace(tmp_path: Path) -> None:
    history = _History({}, service=_Service())
    agent = SimpleNamespace(workspace_dir=None, get_artifacts_dir=lambda: None)
    assert resolve_launch_row(agent, history=history, service=history.service) is None


def test_scope_for_event_prefers_cwd() -> None:
    service = _Service()
    scope = scope_for_event(_event(project="", cwd="/tmp/repo"), service)
    assert scope is not None


def test_launch_chip_type_is_memory_version_chip() -> None:
    row = MemoryLaunchRow(
        display="AGENTS.md",
        chip=MemoryVersionChip("≡ now", "dim"),
        blob_oid=BLOB_A,
        ordinal=3,
    )
    assert row.chip is not None
    assert row.chip.as_text().plain.strip() == "≡ now"


def test_enrichment_never_delays_first_publish() -> None:
    """Rows publish without chips; enrichment adds them in a later pass."""
    from types import SimpleNamespace as _NS

    from sase.ace.tui.memory_reads import MemoryReadDisplayEvent as _Display
    from sase.ace.tui.widgets.prompt_panel._agent_display_header_summary import (
        enrich_memory_versions,
    )
    from sase.ace.tui.widgets.prompt_panel._agent_display_state import (
        DetailHeaderSummary,
    )
    from sase.memory.read_log import READ_LOG_SCHEMA_VERSION, MemoryReadEvent

    event = MemoryReadEvent(
        schema_version=READ_LOG_SCHEMA_VERSION,
        id="first-publish-read",
        timestamp="2026-05-24T14:20:08+00:00",
        project="",
        cwd="/tmp/repo",
        canonical_path="gotchas.md",
        resolved_path="/tmp/repo/gotchas.md",
        agent_name="alpha",
        agent_source="SASE_AGENT_NAME",
        artifacts_dir=None,
        reason="needed it",
        byte_count=64,
        frontmatter_stripped=False,
        selectors=("gotchas.md",),
        blob_oid=BLOB_A,
    )
    first_publish = DetailHeaderSummary(
        memory_reads=(_Display(event=event),),
        ready_lanes=frozenset({"memory"}),
    )
    # The lane's first publish carries rows only.
    assert first_publish.memory_version_chips == {}
    assert first_publish.memory_launch_row is None

    history = _History({BLOB_A: _result(25, now_matches=True)})
    agent = _NS(workspace_dir=None, get_artifacts_dir=lambda: None)
    enriched = enrich_memory_versions(
        first_publish, agent, history=history, service=history.service
    )

    # Rows are untouched; chips arrive in the follow-up pass.
    assert enriched.memory_reads == first_publish.memory_reads
    assert enriched.ready_lanes == frozenset({"memory"})
    assert enriched.memory_version_chips["first-publish-read"].text == "≡ now"
    assert enriched.memory_launch_row is None
