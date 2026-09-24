"""Digest, grouping, and preamble/overlay helper tests for tribe PROMPTS."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich.text import Text

from sase.ace.tui._agent_completion_prompt import (
    prompt_snippet,
    split_prompt_preamble,
)
from sase.ace.tui.models._agent_clan_sections import (
    ClanDiskMemberSnapshot,
    ClanTextEntry,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.util.xprompt_syntax import (
    apply_xprompt_overlays,
    xprompt_overlay_spans,
)
from sase.ace.tui.widgets.prompt_panel import _agent_tribe_prompts as tribe_prompts
from sase.ace.tui.widgets.prompt_panel._agent_tribe_aggregation import TribeUnitSource
from sase.ace.tui.widgets.prompt_panel._agent_tribe_prompts import (
    build_tribe_prompts,
)

_NOW = datetime(2026, 7, 18, 16, 0, 0)


def _agent(name: str, suffix: str, **overrides: object) -> Agent:
    values: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": name,
        "project_file": "/tmp/demo.sase",
        "status": "DONE",
        "start_time": _NOW,
        "stop_time": _NOW,
        "raw_suffix": suffix,
        "agent_name": name,
    }
    values.update(overrides)
    return Agent(**values)  # type: ignore[arg-type]


def _member_snapshot(
    member: Agent,
    label: str,
    xprompt: str | None = None,
    prompt: str | None = None,
) -> ClanDiskMemberSnapshot:
    entries: list[ClanTextEntry] = []
    if xprompt is not None:
        entries.append(
            ClanTextEntry(
                member_identity=member.identity,
                member_label=label,
                kind="AGENT XPROMPT",
                preview=xprompt.splitlines()[0] if xprompt else "",
                body=xprompt,
            )
        )
    if prompt is not None:
        entries.append(
            ClanTextEntry(
                member_identity=member.identity,
                member_label=label,
                kind="AGENT PROMPT",
                preview=prompt.splitlines()[0] if prompt else "",
                body=prompt,
            )
        )
    return ClanDiskMemberSnapshot(
        member_identity=member.identity,
        member_label=label,
        loaded_sections=frozenset({"prompts"}),
        prompts=tuple(entries),
    )


def _source(
    root: Agent,
    label: str,
    rows: tuple[Agent, ...] | None = None,
) -> TribeUnitSource:
    ordered = (root,) if rows is None else rows
    labels = {root.identity: label}
    for row in ordered:
        labels.setdefault(row.identity, row.display_name)
    return TribeUnitSource(
        root=root,
        unit_identity=root.identity,
        unit_label=label,
        rows=ordered,
        labels=labels,
    )


def _digest(raw: str) -> tribe_prompts.PromptDigest:
    agent = _agent("solo", f"solo-{abs(hash(raw)) % 10_000_000}")
    snapshot = build_tribe_prompts(
        (_source(agent, "solo"),),
        {agent.identity: _member_snapshot(agent, "solo", xprompt=raw)},
    )
    assert len(snapshot.groups) == 1
    return snapshot.groups[0].digest


def test_split_preamble_strips_frontmatter_directives_and_vcs_tag() -> None:
    raw = (
        "---\nkind: launch\n---\n"
        "%id(3, clan=sase-16t, bead=sase-16t.3)\n"
        "%model:@medium\n"
        "#gh:sase\n"
        "%auto\n"
        "Do the thing.\nSecond line.\n"
    )
    preamble, body = split_prompt_preamble(raw)

    assert body == "Do the thing.\nSecond line.\n"
    assert "---" not in preamble
    assert "%id(3" in preamble and "#gh:sase" in preamble and "%auto" in preamble


def test_split_preamble_keeps_vcs_tag_between_directive_runs() -> None:
    raw = "%id(1)\n#gh:sase\n%wait:30\n#bd/work_phase_bead:sase-16t.3\n"
    preamble, body = split_prompt_preamble(raw)

    assert body == "#bd/work_phase_bead:sase-16t.3\n"
    assert preamble == "%id(1)\n#gh:sase\n%wait:30"


def test_split_preamble_directives_only_prompt_has_empty_body() -> None:
    preamble, body = split_prompt_preamble("%auto\n%wait:30\n")

    assert body == ""
    assert preamble == "%auto\n%wait:30"


def test_split_preamble_monitor_followup_keeps_heading_body() -> None:
    raw = "%xprompts_enabled:false\n# Monitored command finished\nDetails here.\n"
    preamble, body = split_prompt_preamble(raw)

    assert preamble == "%xprompts_enabled:false"
    assert body == "# Monitored command finished\nDetails here.\n"


def test_prompt_snippet_outputs_are_unchanged() -> None:
    assert prompt_snippet("%id(1) #gh:sase hello world") == "hello world"
    assert (
        prompt_snippet("---\nkind: launch\n---\n%auto\nDo the thing.")
        == "Do the thing."
    )
    assert prompt_snippet("%auto\n") == ""


def test_overlay_spans_match_applied_overlays() -> None:
    source = "#bd/work_phase_bead:sase-16t.3 review the plan %auto\nSecond line.\n"
    applied = Text(source)
    apply_xprompt_overlays(applied, source)
    replayed = Text(source)
    for style, start, end in xprompt_overlay_spans(source):
        replayed.stylize(style, start, end)

    assert [(span.start, span.end, str(span.style)) for span in replayed.spans] == [
        (span.start, span.end, str(span.style)) for span in applied.spans
    ]
    assert xprompt_overlay_spans("x" * 25_000) == ()


def test_digest_joins_hard_wrapped_first_paragraph() -> None:
    digest = _digest(
        "Can you help me split the `src/sase/ace/tui/widgets/prompt_panel`\n"
        "`_settings.py` file up into multiple files?\n"
        "\nSecond paragraph.\n"
    )

    assert digest.headline == (
        "Can you help me split the `src/sase/ace/tui/widgets/prompt_panel` "
        "`_settings.py` file up into multiple files?"
    )
    assert digest.body_line_count == 4


def test_digest_truncates_headline_at_a_word_boundary() -> None:
    digest = _digest("word " * 40 + "\nBody.\n")

    assert len(digest.headline) <= 120
    assert digest.headline.endswith("…")
    assert "…" not in digest.headline[:-1]


def test_digest_uses_xprompt_invocation_with_args_as_headline() -> None:
    digest = _digest("#bd/work_phase_bead:sase-16t.3\n")

    assert digest.headline == "#bd/work_phase_bead:sase-16t.3"
    # The only chip is already visible in the headline, so none remain.
    assert digest.xprompts == ()


def test_digest_strips_heading_markers() -> None:
    digest = _digest("# Monitored command finished\n\nDetails.\n")

    assert digest.headline == "Monitored command finished"


def test_digest_directive_argument_colors_never_become_chips() -> None:
    digest = _digest(
        "%clan(foo, summary=[bold #D75FFF]bar)\nInspect the docs for sase.\n"
    )

    assert digest.xprompts == ()
    assert digest.headline == "Inspect the docs for sase."


def test_digest_falls_back_when_a_helper_raises(monkeypatch: Any) -> None:
    def broken(_body: str) -> str:
        raise RuntimeError("humanize is down")

    monkeypatch.setattr(tribe_prompts, "humanize_prompt_body", broken)
    digest = _digest("Real headline here\nBody line.\n")

    assert digest.headline == "Real headline here"
    assert digest.body == "Real headline here\nBody line.\n"
    assert digest.headline_spans == () and digest.body_spans == ()
    assert digest.xprompts == ()


def test_digest_lru_hit_skips_tokenization(monkeypatch: Any) -> None:
    calls = 0
    real_spans = tribe_prompts.xprompt_overlay_spans

    def counting(source: str, **_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return real_spans(source)

    monkeypatch.setattr(tribe_prompts, "xprompt_overlay_spans", counting)
    raw = "Count tokenization once %auto\nUnique body for lru hit test.\n"
    agent = _agent("lru", "lru-1")
    sources = (_source(agent, "lru"),)
    snapshots = {agent.identity: _member_snapshot(agent, "lru", xprompt=raw)}

    build_tribe_prompts(sources, snapshots)
    first_calls = calls
    assert first_calls > 0
    build_tribe_prompts(sources, snapshots)

    assert calls == first_calls


def test_identical_bodies_with_different_preambles_coalesce_in_order() -> None:
    first = _agent("first", "first")
    second = _agent("second", "second")
    third = _agent("third", "third")
    body = "Inspect the documentation changes.\n"
    snapshot = build_tribe_prompts(
        (
            _source(first, "first"),
            _source(second, "second"),
            _source(third, "third"),
        ),
        {
            first.identity: _member_snapshot(first, "first", xprompt=f"%id(1)\n{body}"),
            second.identity: _member_snapshot(
                second, "second", xprompt=f"%id(2)\n%wait:30\n{body}"
            ),
            third.identity: _member_snapshot(
                third, "third", xprompt="Something else entirely.\n"
            ),
        },
    )

    assert [group.digest.headline for group in snapshot.groups] == [
        "Inspect the documentation changes.",
        "Something else entirely.",
    ]
    assert snapshot.agent_count == 3
    assert [member.unit_label for member in snapshot.groups[0].members] == [
        "first",
        "second",
    ]
    # The group renders its representative's digest.
    assert snapshot.groups[0].digest.launch == "%id(1)"


def test_same_body_in_different_projects_does_not_coalesce() -> None:
    first = _agent("first", "first")
    second = _agent("second", "second")
    body = "Do the shared thing.\n"
    snapshot = build_tribe_prompts(
        (_source(first, "first"), _source(second, "second")),
        {
            first.identity: _member_snapshot(
                first, "first", xprompt=f"#gh:alpha\n{body}"
            ),
            second.identity: _member_snapshot(
                second, "second", xprompt=f"#gh:beta\n{body}"
            ),
        },
    )

    assert len(snapshot.groups) == 2
    assert snapshot.multi_project is True


def test_group_key_is_stable_across_rebuilds() -> None:
    first = _agent("first", "first")
    second = _agent("second", "second")
    members = {
        first.identity: _member_snapshot(first, "first", xprompt="Stable body.\n"),
        second.identity: _member_snapshot(second, "second", xprompt="Other body.\n"),
    }
    sources = (_source(first, "first"), _source(second, "second"))

    assert [
        group.digest.group_key for group in build_tribe_prompts(sources, members).groups
    ] == [
        group.digest.group_key for group in build_tribe_prompts(sources, members).groups
    ]


def test_monitors_gates_and_proc_shells_are_skipped() -> None:
    monitor = _agent(
        "fam--mon",
        "mon",
        agent_session="fam",
        agent_session_role="monitor",
        role_suffix="--mon",
    )
    gate = _agent(
        "fam--gate",
        "gate",
        agent_session="fam",
        agent_session_role="gate",
        gate_id="gate-visual-123",
    )
    proc = _agent("shell", "shell", agent_type=AgentType.PROC_SHELL)
    assert monitor.is_monitor and gate.is_gate and proc.is_proc_shell
    snapshot = build_tribe_prompts(
        (
            _source(monitor, "monitor"),
            _source(gate, "gate"),
            _source(proc, "proc"),
        ),
        {
            member.identity: _member_snapshot(member, "row", xprompt="Body.\n")
            for member in (monitor, gate, proc)
        },
    )

    assert snapshot.groups == () and snapshot.agent_count == 0


def test_workflow_step_children_use_only_their_step_prompt() -> None:
    shell_step = _agent(
        "wf-step",
        "shell-step",
        parent_workflow="wf",
        step_name="shell",
        step_type="shell",
    )
    agent_step = _agent(
        "wf-agent",
        "agent-step",
        parent_workflow="wf",
        step_name="agent",
        step_type="agent",
    )
    assert shell_step.is_workflow_step_child and agent_step.is_workflow_step_child
    snapshot = build_tribe_prompts(
        (
            _source(shell_step, "shell-step", rows=(shell_step,)),
            _source(agent_step, "agent-step", rows=(agent_step,)),
        ),
        {
            shell_step.identity: _member_snapshot(
                shell_step,
                "shell-step",
                xprompt="Parent raw xprompt, never attributed.\n",
                prompt="Shell step body.\n",
            ),
            agent_step.identity: _member_snapshot(
                agent_step,
                "agent-step",
                xprompt="Parent raw xprompt, never attributed.\n",
                prompt="Agent step body.\n",
            ),
        },
    )

    assert [group.digest.headline for group in snapshot.groups] == ["Agent step body."]


def test_agent_prompt_is_used_only_as_a_fallback() -> None:
    legacy = _agent("legacy", "legacy")
    snapshot = build_tribe_prompts(
        (_source(legacy, "legacy"),),
        {
            legacy.identity: _member_snapshot(
                legacy, "legacy", prompt="Historical prompt body.\n"
            )
        },
    )

    assert [group.digest.headline for group in snapshot.groups] == [
        "Historical prompt body."
    ]


def test_missing_snapshots_and_prompts_are_skipped() -> None:
    present = _agent("present", "present")
    missing = _agent("missing", "missing")
    empty = _agent("empty", "empty")
    snapshot = build_tribe_prompts(
        (
            _source(present, "present"),
            _source(missing, "missing"),
            _source(empty, "empty"),
        ),
        {
            present.identity: _member_snapshot(
                present, "present", xprompt="Present body.\n"
            ),
            empty.identity: _member_snapshot(empty, "empty"),
        },
    )

    assert snapshot.agent_count == 1
    assert snapshot.groups[0].digest.headline == "Present body."
