from __future__ import annotations

from sase.agents_sync.rendering_variables import (
    render_agent_variables,
    render_family_variables,
)
from sase.agents_sync.v2_models import V2RunRecord


def _run(
    run_id: str,
    variables: dict[str, object],
) -> V2RunRecord:
    return V2RunRecord(
        run_id,
        f"family--{run_id}",
        f"alice.athena.family--{run_id}",
        "completed",
        metadata=(("output_variables", variables),),
    )


def test_agent_variables_render_inline_previews_and_container_blocks() -> None:
    run = _run(
        "code",
        {
            "status": "ready",
            "config": {
                "z_suites": ["unit", "integration"],
                "a_retries": 3,
                "enabled": True,
                "optional": None,
            },
            "empty": [],
        },
    )

    first = render_agent_variables(
        run,
        source_path="agents/alice.athena.family--code/README.md",
    )
    second = render_agent_variables(
        run,
        source_path="agents/alice.athena.family--code/README.md",
    )
    rendered = "\n".join(first)

    assert first == second
    assert first[:4] == [
        "## Variables",
        "",
        "| Variable | Value |",
        "|---|---|",
    ]
    assert (
        "| `config` | {a\\_retries: 3, enabled: true, optional: null, "
        "z\\_suites: \\[unit, integration\\]} |" in rendered
    )
    assert "| `empty` | \\[\\] |" in rendered
    assert "| `status` | ready |" in rendered
    assert rendered.index("| `config` |") < rendered.index("| `empty` |")
    assert rendered.index("| `empty` |") < rendered.index("| `status` |")
    assert (
        "#### config\n\n```yaml\n"
        "a_retries: 3\n"
        "enabled: true\n"
        "optional: null\n"
        "z_suites:\n"
        "  - unit\n"
        "  - integration\n"
        "```"
    ) in rendered
    assert "#### empty\n\n```yaml\n[]\n```" in rendered


def test_family_container_blocks_retain_member_attribution() -> None:
    rendered = "\n".join(
        render_family_variables(
            (
                ("plan", _run("plan", {"config": {"phase": "plan"}})),
                ("code", _run("code", {"config": {"phase": "code"}})),
            )
        )
    )

    assert rendered.index("| code | `config` |") < rendered.index("| plan | `config` |")
    assert ("#### config\n\n**Role:** `code`\n\n```yaml\nphase: code\n```") in rendered
    assert ("#### config\n\n**Role:** `plan`\n\n```yaml\nphase: plan\n```") in rendered


def test_container_block_and_preview_truncation_is_visible_and_bounded() -> None:
    rendered = "\n".join(
        render_agent_variables(
            _run("code", {"many": [f"item-{index}" for index in range(300)]}),
            source_path="agents/alice.athena.family--code/README.md",
        )
    )

    assert "| `many` |" in rendered
    assert "…" in rendered
    block = rendered.split("```yaml\n", 1)[1].split("\n```", 1)[0]
    assert len(block.splitlines()) <= 200
    assert len(block.encode("utf-8")) <= 16 * 1024
    assert (
        "Values are truncated for display; see [meta.json](meta.json) "
        "for the full values." in rendered
    )


def test_container_block_uses_a_fence_longer_than_nested_backticks() -> None:
    rendered = "\n".join(
        render_agent_variables(
            _run("code", {"config": {"command": "```shell"}}),
            source_path="agents/alice.athena.family--code/README.md",
        )
    )

    assert '````yaml\ncommand: "```shell"\n````' in rendered
