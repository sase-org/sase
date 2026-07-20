"""Tests for launch preview construction and rendering."""

from __future__ import annotations

from pathlib import Path

from sase.agent.launch_executor_types import LaunchExecutionContext
from sase.agent.launch_preview import (
    build_launch_preview_request,
    render_launch_preview_markdown,
)
from sase.core.agent_launch_facade import plan_fake_fanout


def _context(tmp_path: Path) -> LaunchExecutionContext:
    return LaunchExecutionContext(
        cl_name="demo",
        project_file=str(tmp_path / "project.sase"),
        project_name="demo",
        vcs_ref=("gh", "feature"),
    )


def test_launch_preview_request_covers_batch(tmp_path: Path) -> None:
    plan = plan_fake_fanout("multi_prompt", ["first prompt", "second prompt"])
    request = build_launch_preview_request(
        plan=plan,
        context=_context(tmp_path),
        source_surface="agent",
        request_id="launch-test",
        submitted_prompt="first prompt\n---\nsecond prompt",
        slot_planned_names={0: "demo.1", 1: "demo.2"},
        created_at_unix=10.0,
    )

    assert request["request_id"] == "launch-test"
    assert request["all_or_nothing"] is True
    assert request["slot_count"] == 2
    assert request["slots"][0]["planned_name"] == "demo.1"
    assert request["slots"][0]["workspace"]["vcs_ref"] == "feature"
    assert request["slots"][0]["prompt_sha256"]
    assert request["plan"]["slots"][1]["prompt"] == "second prompt"


def test_launch_preview_markdown_renders_full_prompt(tmp_path: Path) -> None:
    full_prompt = "\n".join(
        [
            "%i:demo-review",
            "Keep the line structure intact.",
            "x" * 540,
            "#plan",
            "`actstat --repo sase`",
        ]
    )
    request = build_launch_preview_request(
        plan=plan_fake_fanout("agent", [full_prompt]),
        context=_context(tmp_path),
        source_surface="agent_skill",
        request_id="launch-full",
        slot_planned_names={0: "demo.review"},
        created_at_unix=10.0,
    )
    request["slots"][0]["prompt_snippet"] = "truncated snippet only"

    preview = render_launch_preview_markdown(request)

    assert preview.startswith("# Launch Preview\n\n")
    assert (
        "**1 agent** · source `agent_skill` · all-or-nothing · request `launch-full`"
        in preview
    )
    assert "## Agent 1 of 1 · demo" in preview
    assert "model `default` · kind `agent` · name `demo.review`" in preview
    assert f"```sase\n{full_prompt}\n```" in preview
    assert "truncated snippet only" not in preview
    assert f"SHA-256 `{request['slots'][0]['prompt_sha256'][:12]}`" in preview


def test_launch_preview_markdown_uses_safe_fence_for_backticks(
    tmp_path: Path,
) -> None:
    prompt = "\n".join(
        [
            "Explain this embedded fence:",
            "```python",
            "print('hello')",
            "```",
            "and then continue.",
        ]
    )
    request = build_launch_preview_request(
        plan=plan_fake_fanout("agent", [prompt]),
        context=_context(tmp_path),
        source_surface="agent",
        request_id="launch-fence",
        created_at_unix=10.0,
    )

    preview = render_launch_preview_markdown(request)

    assert f"````sase\n{prompt}\n````" in preview


def test_launch_preview_models_come_from_prompt_directives(tmp_path: Path) -> None:
    plan = plan_fake_fanout(
        "multi_prompt",
        [
            "#git:nova %model:claude-sonnet-4-6\nAudit parser handling.",
            "#git:nova %model:gpt-5-codex\nAdd parser tests.",
            "#git:nova %model:gemini-2.5-pro\nReview release notes.",
        ],
    )
    request = build_launch_preview_request(
        plan=plan,
        context=_context(tmp_path),
        source_surface="ace",
        request_id="launch-models",
        submitted_prompt="ignored",
        created_at_unix=10.0,
    )

    models = [slot["model"] for slot in request["slots"]]
    assert models == [
        "claude-sonnet-4-6",
        "gpt-5-codex",
        "gemini-2.5-pro",
    ]

    preview = render_launch_preview_markdown(request)
    assert (
        "**3 agents** · source `ace` · all-or-nothing · models "
        "`claude-sonnet-4-6`, `gpt-5-codex`, `gemini-2.5-pro` · "
        "request `launch-models`"
    ) in preview
    assert "model `claude-sonnet-4-6`" in preview
    assert "model `gpt-5-codex`" in preview
    assert "model `gemini-2.5-pro`" in preview


def test_launch_preview_renders_model_alias_overrides(tmp_path: Path) -> None:
    request = build_launch_preview_request(
        plan=plan_fake_fanout(
            "agent",
            ["%m(opus, coder=sonnet, phase_worker=@coder)\nImplement"],
        ),
        context=_context(tmp_path),
        source_surface="ace",
        request_id="launch-overrides",
        created_at_unix=10.0,
    )

    assert request["slots"][0]["model_alias_overrides"] == {
        "coder": "sonnet",
        "phase_worker": "@coder",
    }
    preview = render_launch_preview_markdown(request)
    assert (
        "model `opus` · alias overrides: coder → sonnet, phase_worker → @coder"
    ) in preview


def test_launch_preview_annotates_rootless_clan_members(tmp_path: Path) -> None:
    request = build_launch_preview_request(
        plan=plan_fake_fanout(
            "multi_prompt",
            [
                "%id:demo.phase-a\n%clan:demo\nImplement",
                "%id:demo.land\n%clan:demo\nLand the clan",
                "%id:demo.review\n%clan:demo\nReview",
            ],
        ),
        context=_context(tmp_path),
        source_surface="agent_skill",
        request_id="launch-clan",
        created_at_unix=10.0,
    )

    preview = render_launch_preview_markdown(request)

    assert preview.count("clan `demo`") == 3
    assert "family root" not in preview


def test_launch_preview_annotates_clan_tribe(tmp_path: Path) -> None:
    request = build_launch_preview_request(
        plan=plan_fake_fanout(
            "multi_prompt",
            ["%id:demo.phase\n%clan(demo, tribe=quality)\nImplement"],
        ),
        context=_context(tmp_path),
        source_surface="agent_skill",
        request_id="launch-clan-tribe",
        created_at_unix=10.0,
    )

    preview = render_launch_preview_markdown(request)

    assert "clan `demo` · tribe `@quality`" in preview
