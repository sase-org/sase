"""Loader ``fresh`` bypass, slow-finalizer end-to-end, and cache bounds.

Live-tail coverage (epic sase-1b2, bead sase-1b2.18, ``final-live``):
the loader's ``fresh`` bypass (which keeps the tick's elapsed header
honest) without touching the filesystem, the slow retrying finalizer
that projects an active tail end to end, and the final-result cache
bounds.
"""

from __future__ import annotations

import json
import os
import sys
import time as _time

from pathlib import Path

import pytest
from rich.text import Text

from sase.ace.tui.widgets.decks.final.document import build_final_deck_document
from sase.ace.tui.widgets.decks.final.loader import (
    FinalDeckLoadResult,
    cached_final_result,
    clear_final_cache,
    load_final_deck,
    store_final_result,
)
from sase.core.finalizer_run_view import FinalizerNodeView
from tests.ace.tui.widgets.decks.final._final_live_shared import NOW

__all__ = [
    "test_loader_fresh_bypass_rebuilds_for_tick",
    "test_slow_retrying_finalizer_projects_active_tail_end_to_end",
    "test_store_final_result_bounds_cache",
]


# Loader fresh bypass -----------------------------------------------------


def test_loader_fresh_bypass_rebuilds_for_tick() -> None:
    clear_final_cache()
    try:
        from sase.ace.tui.widgets.decks.final import loader as loader_mod
        from sase.finalizers.run_view_inputs import RunTarget

        calls: list[str] = []
        first = FinalizerNodeView(schema_version=1, status="", glyph="")
        second = FinalizerNodeView(schema_version=1, status="!", glyph="!")
        current = {"view": first}

        def _fake_project(targets: object) -> object:
            calls.append("project")
            return current["view"]

        original = loader_mod.project_node_view
        loader_mod.project_node_view = _fake_project  # type: ignore[method-assign]
        try:
            targets = (
                RunTarget(run_id="run-a", artifacts_dir=None, label="agent turn"),
            )
            one = load_final_deck(
                targets, subject="s", subject_identity="s", generation=1
            )
            assert calls == ["project"]
            two = load_final_deck(
                targets, subject="s", subject_identity="s", generation=1
            )
            assert calls == ["project"]
            assert two is not one
            assert cached_final_result("s", two.signature) is not None
            current["view"] = second
            three = load_final_deck(
                targets,
                subject="s",
                subject_identity="s",
                generation=2,
                live_tail_delay=0.0,
                live_now=NOW,
                fresh=True,
            )
            assert calls == ["project", "project"]
            assert three.status == "!"
            assert isinstance(three, FinalDeckLoadResult)
        finally:
            loader_mod.project_node_view = original  # type: ignore[method-assign]
    finally:
        clear_final_cache()


def test_slow_retrying_finalizer_projects_active_tail_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fake slow finalizer: warns, retries, and stays live mid-run.

    A sealed plan plus an open journal (live runner, no ``phase_finished``)
    with a retained ``.live`` sink projects an ``active`` run whose latest
    attempt carries the live tail; the FINAL document renders it in-card
    only once the tail-delay gate opens.
    """
    from sase.core.finalizer_run_view import project_finalizer_node_view
    from sase.core.process_identity import process_identity_token
    from sase.finalizers.plan import resolve_and_persist_finalizer_plan
    from sase.finalizers.progress import ProgressJournal
    from sase.finalizers.run_view_inputs import RunTarget, build_node_request
    from sase.llm_provider.commit_finalizer_types import DirtyState
    from sase.macro.directives import PromptDirectives
    from tests.finalizers_live_e2e_test_helpers import (
        command_instance,
        config_for,
        use_config,
    )

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True)
    use_config(
        monkeypatch,
        config_for(
            {"slow-check": command_instance("slow-check", [sys.executable, "-c", "1"])},
            ("slow-check",),
        ),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: DirtyState(project_dir=str(artifacts), repos=(), details=""),
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-1")
    monkeypatch.setenv("SASE_FINAL_TURN_NONCE", "nonce-1")
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(artifacts))
    (artifacts / "agent_meta.json").write_text("{}", encoding="utf-8")
    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))

    started = _time.time() - 30.0
    journal = ProgressJournal(str(artifacts))
    journal.record(
        "phase_started",
        run_id="slow-run",
        plan_digest="digest-slow",
        mode="normal",
        runner={"pid": os.getpid(), "identity": process_identity_token(os.getpid())},
    )
    journal.record("cycle_started", cycle=1)
    journal.record("instance_started", instance_id="slow-check")
    journal.record(
        "attempt_started", instance_id="slow-check", attempt=1, max_attempts=2
    )
    journal.record(
        "op_started",
        instance_id="slow-check",
        attempt=1,
        op="command",
        kind="subprocess",
        label="just check",
    )
    journal.record(
        "attempt_finished",
        instance_id="slow-check",
        attempt=1,
        max_attempts=2,
        status="failed",
        code="command_failed",
    )
    journal.record(
        "attempt_started", instance_id="slow-check", attempt=2, max_attempts=2
    )
    journal.record(
        "op_started",
        instance_id="slow-check",
        attempt=2,
        op="command",
        kind="subprocess",
        label="just check",
    )
    inst_dir = artifacts / "finalizers" / "slow-check"
    inst_dir.mkdir(parents=True, exist_ok=True)
    (inst_dir / "attempt-1.command.outcome.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "op": "command",
                "kind": "subprocess",
                "label": "just check",
                "attempt": 1,
                "started_at": started - 120.0,
                "duration_seconds": 41.2,
                "returncode": 1,
                "timed_out": False,
            }
        ),
        encoding="utf-8",
    )
    (inst_dir / "attempt-2.command.outcome.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "op": "command",
                "kind": "subprocess",
                "label": "just check",
                "attempt": 2,
                "started_at": started,
                "timed_out": False,
            }
        ),
        encoding="utf-8",
    )
    (inst_dir / "attempt-2.command.steps.jsonl").write_text(
        json.dumps(
            {"v": 1, "t": started + 1.0, "step": "running checks", "state": "start"}
        )
        + "\n"
        + json.dumps(
            {
                "v": 1,
                "t": started + 2.0,
                "step": "slow network",
                "state": "warn",
                "detail": "retrying",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (inst_dir / "attempt-2.command.live").write_text(
        "checking tests/ace […]\x1b[33mwarn: slow network\x1b[0m\n"
        "downloading\rdownloading 42%\n",
        encoding="utf-8",
    )

    request = build_node_request(
        [
            RunTarget(
                run_id="run-1",
                artifacts_dir=str(artifacts),
                turn_terminal=False,
            )
        ]
    )
    view = project_finalizer_node_view(request)
    assert view.runs[0].disposition == "active"
    instance = view.runs[0].instances[0]
    assert instance.instance_id == "slow-check"
    assert [(item.attempt, item.status) for item in instance.attempts] == [
        (1, "failed"),
        (2, "running"),
    ]
    live_ops = [op for op in instance.operations if op.live_tail]
    assert len(live_ops) == 1
    assert live_ops[0].attempt == 2
    assert any("slow network" in line for line in live_ops[0].live_tail)
    # Carriage-return progress collapses to its last segment.
    assert any("downloading 42%" in line for line in live_ops[0].live_tail)

    document = build_final_deck_document(
        view, subject="e2e", digest="d", live_tail_delay=0, live_now=_time.time()
    )
    flat = "\n".join(
        part.plain
        for card in document.cards
        for part in card.renderables
        if isinstance(part, Text)
    )
    assert "downloading 42%" in flat
    assert "slow network" in flat
    # Before the gate opens the card stays a bare running op.
    early = build_final_deck_document(
        view, subject="e2e", digest="d", live_tail_delay=5.0, live_now=started + 1.0
    )
    early_flat = "\n".join(
        part.plain
        for card in early.cards
        for part in card.renderables
        if isinstance(part, Text)
    )
    assert "downloading 42%" not in early_flat


def test_store_final_result_bounds_cache() -> None:
    clear_final_cache()
    try:
        from sase.ace.tui.widgets.decks.final import loader as loader_mod

        for index in range(loader_mod.FINAL_CACHE_SIZE + 5):
            store_final_result(
                FinalDeckLoadResult(
                    subject_identity=f"subject-{index}",
                    generation=1,
                    signature=f"sig-{index}",
                    document=object(),
                    default_card=None,
                    status="",
                    glyph="",
                    attention_instance_id=None,
                    run_level_trouble=False,
                )
            )
        assert len(loader_mod._FINAL_CACHE) == loader_mod.FINAL_CACHE_SIZE
    finally:
        clear_final_cache()
