"""Live-tail coverage (epic sase-1b2, bead sase-1b2.18, ``final-live``).

The tail gate, sanitization, newest-run/latest-attempt following, the
scroll follow-pause state, the 1 Hz tick predicates, and the in-card
tail rendering over the real projection dataclasses. The loader's
``fresh`` bypass (which keeps the tick's elapsed header honest) is
covered without touching the filesystem.
"""

from __future__ import annotations

import json
import os
import sys
import time as _time

from pathlib import Path
from types import SimpleNamespace

import pytest
from rich.text import Text

from sase.ace.tui.widgets.decks.final.document import build_final_deck_document
from sase.ace.tui.widgets.decks.final.instance_card import (
    build_instance_card_renderables,
)
from sase.ace.tui.widgets.decks.final.live import (
    FINAL_LIVE_TAIL_MAX_LINES,
    FinalLiveTicker,
    LiveFollowTarget,
    _LiveFollowState,
    _format_live_elapsed,
    _is_operation_active,
    _live_tail_lines_for_operation,
    _sanitize_live_tail_lines,
    _should_live_tick,
    _tail_gate_open,
    finalization_active,
    select_live_follow_target,
)
from sase.ace.tui.widgets.decks.final.loader import (
    FinalDeckLoadResult,
    cached_final_result,
    clear_final_cache,
    load_final_deck,
    store_final_result,
)
from sase.core.finalizer_run_view import (
    FinalizerNodeView,
    RunViewAttempt,
    RunViewNodeInstance,
    RunViewOperation,
    RunViewRun,
    RunViewRunInstance,
)

NOW = 1_800_000_000.0


def _text(renderables: tuple[object, ...]) -> str:
    parts: list[str] = []
    for renderable in renderables:
        if isinstance(renderable, Text):
            parts.append(renderable.plain)
        else:
            parts.append(str(renderable))
    return "\n".join(parts)


def _active_op(**kwargs: object) -> RunViewOperation:
    base: dict[str, object] = {
        "op": "just check",
        "kind": "subprocess",
        "label": "just check",
        "attempt": 1,
        "started_at": NOW - 30.0,
        "returncode": None,
        "live_tail": ["line one", "line two"],
    }
    base.update(kwargs)
    return RunViewOperation(**base)  # type: ignore[arg-type]


def _run_instance(op: RunViewOperation, **kwargs: object) -> RunViewRunInstance:
    base: dict[str, object] = {
        "instance_id": "check",
        "status": "running",
        "attempts": [RunViewAttempt(attempt=1, status="running")],
        "operations": [op],
        "attempt": 1,
        "max_attempts": 1,
        "op": "just check",
    }
    base.update(kwargs)
    return RunViewRunInstance(**base)  # type: ignore[arg-type]


def _run(run_id: str, item: RunViewRunInstance, **kwargs: object) -> RunViewRun:
    base: dict[str, object] = {
        "run_id": run_id,
        "number": 0,
        "label": run_id,
        "kind": "agent",
        "disposition": "active",
        "instances": [item],
    }
    base.update(kwargs)
    return RunViewRun(**base)  # type: ignore[arg-type]


def _node(instance_id: str, runs: list[RunViewRun]) -> FinalizerNodeView:
    return FinalizerNodeView(
        schema_version=1,
        status="running",
        glyph="▶",
        instances=[
            RunViewNodeInstance(
                instance_id=instance_id,
                selection_reason="default",
                status="running",
            )
        ],
        runs=runs,
    )


# Gate -----------------------------------------------------------------


def test_tail_gate_delay_zero_renders_immediately() -> None:
    assert _tail_gate_open(op_started_at=NOW, now=NOW, delay_seconds=0)
    assert _tail_gate_open(op_started_at=None, now=NOW, delay_seconds=0)
    assert _tail_gate_open(op_started_at=NOW, now=NOW, delay_seconds=-1.0)


def test_tail_gate_holds_fast_ops() -> None:
    assert not _tail_gate_open(op_started_at=NOW - 1.0, now=NOW, delay_seconds=5.0)
    assert _tail_gate_open(op_started_at=NOW - 5.0, now=NOW, delay_seconds=5.0)
    assert _tail_gate_open(op_started_at=NOW - 30.0, now=NOW, delay_seconds=5.0)


def test_tail_gate_unknown_start_stays_closed() -> None:
    assert not _tail_gate_open(op_started_at=None, now=NOW, delay_seconds=5.0)
    assert not _tail_gate_open(op_started_at=True, now=NOW, delay_seconds=5.0)
    assert not _tail_gate_open(op_started_at="soon", now=NOW, delay_seconds=5.0)


# Sanitize --------------------------------------------------------------


def test_sanitize_caps_at_twelve_lines() -> None:
    lines = [f"line {index}" for index in range(30)]
    assert _sanitize_live_tail_lines(lines) == [
        f"line {index}" for index in range(18, 30)
    ]
    assert FINAL_LIVE_TAIL_MAX_LINES == 12


def test_sanitize_collapses_carriage_returns() -> None:
    assert _sanitize_live_tail_lines(["first\rsecond", "plain"]) == ["second", "plain"]
    assert _sanitize_live_tail_lines("not-a-list") == []
    assert _sanitize_live_tail_lines(None) == []


# Active + follow selection ---------------------------------------------


def test_finalization_active_phases() -> None:
    assert finalization_active(SimpleNamespace(phase="declaring"))
    assert finalization_active(SimpleNamespace(phase="executing"))
    assert finalization_active({"phase": "executing"})
    assert not finalization_active(SimpleNamespace(phase="planned"))
    assert not finalization_active(SimpleNamespace(phase="settled"))
    assert not finalization_active(SimpleNamespace(phase="skipped"))
    assert not finalization_active(None)
    assert not finalization_active(SimpleNamespace())


def test_is_operation_active_treats_missing_exit_as_running() -> None:
    assert _is_operation_active(_active_op())
    assert not _is_operation_active(_active_op(returncode=0))
    assert not _is_operation_active(_active_op(returncode=1))


def test_follow_target_is_newest_run_with_live_content() -> None:
    old = _run("run-old", _run_instance(_active_op()))
    new = _run("run-new", _run_instance(_active_op()))
    target = select_live_follow_target([old, new])
    assert target == LiveFollowTarget(run_id="run-new", attempt=1)


def test_follow_target_skips_runs_without_live_content() -> None:
    old = _run("run-old", _run_instance(_active_op()))
    quiet = _run(
        "run-quiet",
        _run_instance(_active_op(live_tail=[], returncode=0)),
    )
    assert select_live_follow_target([old, quiet]) == LiveFollowTarget(
        run_id="run-old", attempt=1
    )
    assert select_live_follow_target([quiet]) is None
    assert select_live_follow_target([]) is None


def test_follow_target_names_latest_attempt() -> None:
    op_new = _active_op(attempt=2)
    item = _run_instance(
        op_new,
        attempts=[
            RunViewAttempt(attempt=1, status="failed"),
            RunViewAttempt(attempt=2, status="running"),
        ],
    )
    target = select_live_follow_target([_run("run-a", item)])
    assert target == LiveFollowTarget(run_id="run-a", attempt=2)


def test_live_lines_scoped_to_follow_target() -> None:
    op = _active_op()
    follow = LiveFollowTarget(run_id="run-new", attempt=1)
    assert _live_tail_lines_for_operation(
        op, delay_seconds=0, now=NOW, follow=follow, run_id="run-new"
    ) == ["line one", "line two"]
    assert (
        _live_tail_lines_for_operation(
            op, delay_seconds=0, now=NOW, follow=follow, run_id="run-old"
        )
        == []
    )
    assert (
        _live_tail_lines_for_operation(
            op,
            delay_seconds=0,
            now=NOW,
            follow=LiveFollowTarget(run_id="run-new", attempt=2),
            run_id="run-new",
        )
        == []
    )
    # Unscoped ops (no attempt number) still render under the follow run.
    assert _live_tail_lines_for_operation(
        _active_op(attempt=None),
        delay_seconds=0,
        now=NOW,
        follow=follow,
        run_id="run-new",
    ) == ["line one", "line two"]


def test_live_lines_require_active_op_and_open_gate() -> None:
    assert (
        _live_tail_lines_for_operation(
            _active_op(returncode=0), delay_seconds=0, now=NOW
        )
        == []
    )
    assert (
        _live_tail_lines_for_operation(
            _active_op(started_at=NOW - 1.0), delay_seconds=5.0, now=NOW
        )
        == []
    )
    assert _live_tail_lines_for_operation(
        _active_op(started_at=NOW - 30.0), delay_seconds=5.0, now=NOW
    ) == ["line one", "line two"]


# Follow pause + tick predicates -----------------------------------------


def test_follow_pause_and_resume() -> None:
    state = _LiveFollowState()
    assert state.paused is False
    assert state.note_scroll(at_bottom=True) is False
    assert state.paused is False
    assert state.note_scroll(at_bottom=False) is False
    assert state.paused is True
    # Still scrolled up: no refresh due.
    assert state.note_scroll(at_bottom=False) is False
    # Back at the bottom: resume with one refresh.
    assert state.note_scroll(at_bottom=True) is True
    assert state.paused is False
    assert state.note_scroll(at_bottom=True) is False


def test_format_live_elapsed() -> None:
    assert _format_live_elapsed(NOW - 12.0, NOW) == "12s"
    assert _format_live_elapsed(NOW - 184.0, NOW) == "3m04s"
    assert _format_live_elapsed(None, NOW) is None
    assert _format_live_elapsed(NOW + 5.0, NOW) is None


def test_should_live_tick_scope() -> None:
    good = {
        "visible": True,
        "active": True,
        "navigating": False,
        "typing": False,
        "paused": False,
        "in_flight": False,
    }
    assert _should_live_tick(**good) is True
    for key in good:
        blocked = dict(good)
        blocked[key] = not blocked[key] if key in ("visible", "active") else True
        if key in ("visible", "active"):
            assert _should_live_tick(**blocked) is False, key
        else:
            assert _should_live_tick(**blocked) is False, key


def test_ticker_coalesces_in_flight_and_pause() -> None:
    ticker = FinalLiveTicker()
    assert (
        ticker.want_tick(visible=True, active=True, navigating=False, typing=False)
        is True
    )
    assert ticker.begin() is True
    assert ticker.begin() is False
    assert (
        ticker.want_tick(visible=True, active=True, navigating=False, typing=False)
        is False
    )
    ticker.finish()
    assert (
        ticker.want_tick(visible=True, active=True, navigating=False, typing=False)
        is True
    )
    assert ticker.note_scroll(at_bottom=False) is False
    assert (
        ticker.want_tick(visible=True, active=True, navigating=False, typing=False)
        is False
    )
    assert ticker.note_scroll(at_bottom=True) is True


# Card rendering ----------------------------------------------------------


def test_card_renders_gated_live_tail_for_active_op() -> None:
    runs = [_run("run-a", _run_instance(_active_op()))]
    node = _node("check", runs)
    body = _text(
        build_instance_card_renderables(
            node.instances[0], runs, live_delay_seconds=0, live_now=NOW
        )
    )
    assert "live · 30s" in body
    assert "line one" in body
    assert "line two" in body


def test_card_hides_tail_before_gate_opens() -> None:
    runs = [_run("run-a", _run_instance(_active_op(started_at=NOW - 1.0)))]
    node = _node("check", runs)
    body = _text(
        build_instance_card_renderables(
            node.instances[0], runs, live_delay_seconds=5.0, live_now=NOW
        )
    )
    assert "line one" not in body
    assert "live" not in body


def test_card_hides_tail_for_settled_ops() -> None:
    runs = [_run("run-a", _run_instance(_active_op(returncode=0, live_tail=["stale"])))]
    node = _node("check", runs)
    body = _text(
        build_instance_card_renderables(
            node.instances[0], runs, live_delay_seconds=0, live_now=NOW
        )
    )
    assert "stale" not in body


def test_card_tails_follow_newest_run_only() -> None:
    old_op = _active_op(live_tail=["old tail"])
    new_op = _active_op(live_tail=["new tail"])
    runs = [
        _run("run-old", _run_instance(old_op)),
        _run("run-new", _run_instance(new_op)),
    ]
    node = _node("check", runs)
    body = _text(
        build_instance_card_renderables(
            node.instances[0], runs, live_delay_seconds=0, live_now=NOW
        )
    )
    assert "new tail" in body
    assert "old tail" not in body


def test_card_tail_never_bleeds_across_agents() -> None:
    runs_a = [_run("run-a", _run_instance(_active_op(live_tail=["agent A tail"])))]
    runs_b = [_run("run-b", _run_instance(_active_op(live_tail=["agent B tail"])))]
    body_a = _text(
        build_instance_card_renderables(
            _node("check", runs_a).instances[0],
            runs_a,
            live_delay_seconds=0,
            live_now=NOW,
        )
    )
    body_b = _text(
        build_instance_card_renderables(
            _node("check", runs_b).instances[0],
            runs_b,
            live_delay_seconds=0,
            live_now=NOW,
        )
    )
    assert "agent A tail" in body_a and "agent B tail" not in body_a
    assert "agent B tail" in body_b and "agent A tail" not in body_b


def test_card_tail_caps_at_twelve_lines() -> None:
    tail = [f"trace {index}" for index in range(20)]
    runs = [_run("run-a", _run_instance(_active_op(live_tail=tail)))]
    node = _node("check", runs)
    body = _text(
        build_instance_card_renderables(
            node.instances[0], runs, live_delay_seconds=0, live_now=NOW
        )
    )
    assert "trace 0" not in body
    assert "trace 19" in body


def test_document_build_threads_live_tail() -> None:
    runs = [_run("run-a", _run_instance(_active_op()))]
    node = _node("check", runs)
    document = build_final_deck_document(
        node, subject="agent-x", digest="d", live_tail_delay=0, live_now=NOW
    )
    assert "agent-x" in document.card_ids or document.cards
    flat = "\n".join(
        part.plain
        for card in document.cards
        for part in card.renderables
        if isinstance(part, Text)
    )
    assert "line one" in flat
    calm = build_final_deck_document(node, subject="agent-x", digest="d")
    calm_flat = "\n".join(
        part.plain
        for card in calm.cards
        for part in card.renderables
        if isinstance(part, Text)
    )
    assert "line one" not in calm_flat


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
    from sase.xprompt.directives import PromptDirectives
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
