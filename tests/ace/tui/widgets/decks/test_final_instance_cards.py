"""Instance-card coverage (epic sase-1b2, bead sase-1b2.16).

The generic renderer plus the commit/command enrichers, proven against a
plugin fixture that must render completely through the generic path.
"""

from __future__ import annotations

from types import SimpleNamespace

from rich.text import Text

from sase.ace.tui.widgets.decks.final.document import build_final_deck_document
from sase.ace.tui.widgets.decks.final.enrichers import instance_enrichments
from sase.ace.tui.widgets.decks.final.instance_card import (
    build_instance_card_renderables,
)
from sase.core.finalizer_run_view import (
    _RunViewAttempt,
    _RunViewDeferral,
    _RunViewEvidence,
    _RunViewInstanceDiagnostic,
    _RunViewLog,
    _RunViewNodeInstance,
    _RunViewOperation,
    RunViewRun,
    RunViewRunInstance,
    _RunViewStep,
)


def _card_text(renderables: tuple[object, ...]) -> str:
    parts: list[str] = []
    for renderable in renderables:
        if isinstance(renderable, Text):
            parts.append(renderable.plain)
        else:
            parts.append(str(renderable))
    return "\n".join(parts)


def _plugin_run_instance() -> RunViewRunInstance:
    return RunViewRunInstance(
        instance_id="open-pr",
        status="failed",
        provider_ref="acme-sase@open-pr",
        selection_reason="%final:open-pr",
        trigger_kind="always",
        submission_required=True,
        obligation_count=2,
        payload_summary={"title": "Add retry", "draft": "true"},
        evidence=[
            _RunViewEvidence(
                kind="pr_url",
                value="https://example.com/pr/42",
                evidence_type="url",
            ),
            _RunViewEvidence(kind="duration", value="95.5", evidence_type="duration"),
            _RunViewEvidence(kind="exit_code", value="1", evidence_type="exit_code"),
        ],
        headline=_RunViewEvidence(
            kind="pr_url",
            value="https://example.com/pr/42",
            evidence_type="url",
        ),
        attempts=[
            _RunViewAttempt(
                attempt=1, status="failed", duration_seconds=95.5, code="execute_failed"
            ),
        ],
        operations=[
            _RunViewOperation(
                op="execute",
                kind="subprocess",
                label="execute",
                attempt=1,
                duration_seconds=95.5,
                returncode=1,
                logs=[
                    _RunViewLog(
                        kind="stdout", name="attempt-1.execute.stdout", line_count=40
                    ),
                    _RunViewLog(
                        kind="stderr", name="attempt-1.execute.stderr", line_count=3
                    ),
                ],
                steps=[
                    _RunViewStep(step="open pull request", state="start"),
                    _RunViewStep(step="push branch", state="ok"),
                    _RunViewStep(step="slow network", state="warn"),
                ],
            ),
        ],
        diagnostics=[
            _RunViewInstanceDiagnostic(
                code="execute_failed",
                message="push rejected",
                severity="error",
                attempt=1,
            ),
        ],
        warnings=1,
        protocol_files=["preflight.describe.outcome.json"],
        attempt=1,
        max_attempts=1,
        failure_reason="push rejected",
    )


def _plugin_node_view() -> SimpleNamespace:
    node = _RunViewNodeInstance(
        instance_id="open-pr",
        selection_reason="%final:open-pr",
        status="failed",
        provider_ref="acme-sase@open-pr",
    )
    run = RunViewRun(
        run_id="run-1",
        number=0,
        label="--code",
        kind="agent",
        disposition="ran",
        instances=[_plugin_run_instance()],
    )
    return SimpleNamespace(
        status="failed",
        glyph="✗",
        run_level_trouble=True,
        instances=[node],
        unselected=[],
        attention_instance_id="open-pr",
        runs=[run],
    )


def test_plugin_fixture_renders_fully_generic() -> None:
    view = _plugin_node_view()
    node = view.instances[0]
    assert instance_enrichments("acme-sase@open-pr", node, view.runs) == ()
    assert instance_enrichments(None, node, view.runs) == ()
    body = _card_text(build_instance_card_renderables(node, view.runs))
    assert "open-pr · acme-sase@open-pr" in body
    assert "why %final:open-pr" in body
    assert "submission required" in body
    assert "2 obligations" in body
    assert "declared draft=true, title=Add retry" in body
    assert "push branch" in body
    assert "⚠ 1 warning (slow network) ›" in body
    assert "https://example.com/pr/42" in body
    assert "exit 1" in body
    assert "push rejected" in body
    assert "protocol preflight.describe.outcome.json   v to open" in body
    assert "attempt-1.execute.stdout (40 lines)" in body
    assert "command detail" not in body
    assert "commit detail" not in body


def test_plugin_card_lands_in_deck_document() -> None:
    document = build_final_deck_document(_plugin_node_view(), subject="a:1", digest="s")
    assert document.card_ids == ("overview", "instance:open-pr")
    card = document.card("instance:open-pr")
    assert card is not None
    assert card.title == "open-pr ✗"
    body = _card_text(tuple(card.renderables))
    assert "https://example.com/pr/42" in body


def test_commit_enricher_renders_sha_table() -> None:
    node = _RunViewNodeInstance(
        instance_id="commit",
        selection_reason="default",
        status="success",
        provider_ref="builtin@commit",
    )
    run_item = RunViewRunInstance(
        instance_id="commit",
        status="success",
        provider_ref="builtin@commit",
        evidence=[
            _RunViewEvidence(
                kind="commit_sha", value="8bb7e551234abcd", evidence_type="sha"
            ),
            _RunViewEvidence(kind="bead_id", value="sase-1b2.16", evidence_type="bead"),
        ],
        headline=_RunViewEvidence(
            kind="commit_sha", value="8bb7e551234abcd", evidence_type="sha"
        ),
        attempts=[_RunViewAttempt(attempt=1, status="success", duration_seconds=124.0)],
        operations=[
            _RunViewOperation(
                op="stitch-main",
                kind="internal",
                label="stitch main",
                attempt=1,
                duration_seconds=124.0,
                returncode=0,
            )
        ],
    )
    run = RunViewRun(
        run_id="r",
        number=0,
        label="--code",
        kind="agent",
        disposition="ran",
        instances=[run_item],
    )
    extra = _card_text(instance_enrichments("builtin@commit", node, [run]))
    assert "8bb7e55  ↗ commit view" in extra
    assert "bead sase-1b2.16" in extra
    generic = _card_text(build_instance_card_renderables(node, [run]))
    assert "8bb7e55" in generic
    assert "2m04s" in generic


def test_command_enricher_renders_argv_and_failure() -> None:
    node = _RunViewNodeInstance(
        instance_id="check",
        selection_reason="%final:check",
        status="failed",
        provider_ref="builtin@command",
        after=["commit"],
    )
    run_item = RunViewRunInstance(
        instance_id="check",
        status="failed",
        provider_ref="builtin@command",
        after=["commit"],
        attempts=[
            _RunViewAttempt(
                attempt=1, status="failed", duration_seconds=12.0, code="command_failed"
            ),
            _RunViewAttempt(
                attempt=2,
                status="failed",
                duration_seconds=220.0,
                code="command_failed",
            ),
        ],
        operations=[
            _RunViewOperation(
                op="command",
                kind="subprocess",
                label="just check",
                attempt=1,
                argv=["just", "check"],
                duration_seconds=12.0,
                returncode=1,
            ),
            _RunViewOperation(
                op="command",
                kind="subprocess",
                label="just check",
                attempt=2,
                argv=["just", "check"],
                duration_seconds=220.0,
                returncode=1,
            ),
        ],
        diagnostics=[
            _RunViewInstanceDiagnostic(
                code="command_failed",
                message="FAILED t.py::t",
                severity="error",
                attempt=2,
            ),
        ],
        attempt=2,
        max_attempts=2,
        failure_reason="FAILED t.py::t",
    )
    run = RunViewRun(
        run_id="r",
        number=0,
        label="--code",
        kind="agent",
        disposition="ran",
        instances=[run_item],
    )
    extra = _card_text(instance_enrichments("builtin@command", node, [run]))
    assert "$ just check" in extra
    assert "✗ just check · exit 1" in extra
    generic = _card_text(build_instance_card_renderables(node, [run]))
    assert "attempt 2/2" in generic
    assert "after commit" in generic
    assert "FAILED t.py::t" in generic


def test_attempt_folding_collapses_older_attempts() -> None:
    node = _RunViewNodeInstance(
        instance_id="check",
        selection_reason="default",
        status="success",
        provider_ref="builtin@command",
    )
    run_item = RunViewRunInstance(
        instance_id="check",
        status="success",
        attempts=[
            _RunViewAttempt(
                attempt=1, status="failed", duration_seconds=5.0, code="command_failed"
            ),
            _RunViewAttempt(attempt=2, status="success", duration_seconds=6.0),
        ],
        operations=[
            _RunViewOperation(
                op="command",
                kind="subprocess",
                label="old op",
                attempt=1,
                duration_seconds=5.0,
                returncode=1,
            ),
            _RunViewOperation(
                op="command",
                kind="subprocess",
                label="new op",
                attempt=2,
                duration_seconds=6.0,
                returncode=0,
            ),
        ],
        diagnostics=[
            _RunViewInstanceDiagnostic(
                code="command_failed",
                message="flaked once",
                severity="superseded",
                attempt=1,
            ),
        ],
        max_attempts=2,
    )
    run = RunViewRun(
        run_id="r",
        number=0,
        label="--code",
        kind="agent",
        disposition="ran",
        instances=[run_item],
    )
    body = _card_text(build_instance_card_renderables(node, [run]))
    assert "old op" not in body
    assert "new op" in body
    assert "attempt 1" in body
    assert "(superseded)" in body
    assert "flaked once" in body


def test_warnings_show_only_inside_deck_card() -> None:
    node = _RunViewNodeInstance(
        instance_id="commit",
        selection_reason="default",
        status="success",
        provider_ref="builtin@commit",
    )
    run_item = RunViewRunInstance(
        instance_id="commit",
        status="success",
        warnings=3,
        attempts=[_RunViewAttempt(attempt=1, status="success")],
    )
    run = RunViewRun(
        run_id="r",
        number=0,
        label="--code",
        kind="agent",
        disposition="ran",
        instances=[run_item],
    )
    body = _card_text(build_instance_card_renderables(node, [run]))
    assert "⚠3" in body.splitlines()[0]


def test_unknown_status_renders_neutral() -> None:
    node = _RunViewNodeInstance(
        instance_id="mystery",
        selection_reason="default",
        status="quantum",
        provider_ref="acme@thing",
    )
    body = _card_text(build_instance_card_renderables(node, []))
    assert "• quantum" in body


def test_deferred_paths_cap_with_more_suffix() -> None:
    node = _RunViewNodeInstance(
        instance_id="commit",
        selection_reason="default",
        status="deferred",
        provider_ref="builtin@commit",
    )
    run_item = RunViewRunInstance(
        instance_id="commit",
        status="deferred",
        deferral=_RunViewDeferral(
            reason="unsafe_content",
            paths=[f"secret{i}.env" for i in range(7)],
        ),
        attempts=[_RunViewAttempt(attempt=1, status="deferred")],
    )
    run = RunViewRun(
        run_id="r",
        number=0,
        label="--code",
        kind="agent",
        disposition="ran",
        instances=[run_item],
    )
    body = _card_text(build_instance_card_renderables(node, [run]))
    assert "+2 more" in body
    assert "secret6.env" not in body


def test_refused_and_not_run_blocks_are_calm() -> None:
    refused = RunViewRunInstance(
        instance_id="push",
        status="refused",
        refusal_reason="no network",
        attempts=[_RunViewAttempt(attempt=1, status="refused")],
    )
    blocked = RunViewRunInstance(
        instance_id="tasks",
        status="not_run",
        blocked_by="check",
    )
    run = RunViewRun(
        run_id="r",
        number=0,
        label="--code",
        kind="agent",
        disposition="ran",
        instances=[refused, blocked],
    )
    push = _RunViewNodeInstance(
        instance_id="push", selection_reason="default", status="refused"
    )
    tasks = _RunViewNodeInstance(
        instance_id="tasks", selection_reason="default", status="not_run"
    )
    push_body = _card_text(build_instance_card_renderables(push, [run]))
    assert "⊘ refused: no network" in push_body
    tasks_body = _card_text(build_instance_card_renderables(tasks, [run]))
    assert "not run · blocked by check" in tasks_body


def test_width_tiers_clip_long_lines() -> None:
    view = _plugin_node_view()
    node = view.instances[0]
    for width in (120, 80, 60):
        body = build_instance_card_renderables(node, view.runs, width=width)
        for renderable in body:
            assert isinstance(renderable, Text)
            assert len(renderable.plain) <= width, renderable.plain
        extra = instance_enrichments("builtin@command", node, view.runs, width=width)
        for renderable in extra:
            assert len(renderable.plain) <= width, renderable.plain
