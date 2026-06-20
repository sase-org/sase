"""Phase 5 parity gate: the Tools panel stays provider-neutral for ``agy``.

The Antigravity (``agy``) provider streams plain stdout and writes no
``tool_calls.jsonl`` because Antigravity CLI exposes no stable machine-readable
contract. The ACE Agents-tab Tools panel must therefore surface nothing for an
``agy`` run; it must not learn to scrape ``agy``'s human display text
(``live_reply.md`` prose) into fabricated tool-call rows.
"""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.tools import read_tool_calls_for_agent

from ._reader_helpers import _agent, _tool_use_record, _write_jsonl


def test_agy_run_without_tool_calls_artifact_shows_nothing(tmp_path: Path) -> None:
    """An ``agy`` run writes only ``live_reply.md`` — the panel reads ``None``.

    The reader is the single cross-runtime contract: with no ``tool_calls.jsonl``
    present it returns ``None`` (the Tools panel shows nothing), proving there is
    no ``agy``-specific scraping fallback that mines the plain reply for tools.
    """
    artifacts_dir = tmp_path / "ace-run" / "20260619230000"
    artifacts_dir.mkdir(parents=True)
    # Tool-shaped prose in the plain reply must never become a tool-call row.
    (artifacts_dir / "live_reply.md").write_text(
        "● Running tool: Bash(echo hi)\nfinal agy answer\n",
        encoding="utf-8",
    )

    assert read_tool_calls_for_agent(_agent(artifacts_dir)) is None


def test_tools_panel_contract_is_unchanged_for_agy_runtime(tmp_path: Path) -> None:
    """The panel reads the same normalized contract regardless of runtime.

    There is no ``agy`` source/runtime branch in the reader. If a future
    Antigravity machine-readable contract ever lets SASE emit normalized rows
    (``runtime: "agy"``), they flow through the existing provider-neutral reader
    with no panel changes — this pins that the contract, not display scraping,
    is what the panel consumes.
    """
    artifacts_dir = tmp_path / "ace-run" / "20260619230100"
    _write_jsonl(
        artifacts_dir / "tool_calls.jsonl",
        [
            _tool_use_record(
                tool_use_id="agy-future-call",
                runtime="agy",
                source="stream",
                tool_input_summary={"command": "echo agy"},
            ),
        ],
    )

    entries = read_tool_calls_for_agent(_agent(artifacts_dir))

    assert entries is not None
    assert [(entry.runtime, entry.source) for entry in entries] == [("agy", "stream")]
