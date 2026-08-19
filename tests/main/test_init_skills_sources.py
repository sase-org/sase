"""Tests for shipped ``sase init skills`` source discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.main import init_skills_handler
from sase.main.init_skills_handler import (
    _get_target_path,
    get_skill_target_providers,
    handle_init_skills_command,
)
from sase.xprompt.loader import get_sase_package_skills_dir
from sase.xprompt.loader_parsing import parse_yaml_front_matter
from tests.main.init_skills_handler_helpers import collapse_whitespace, make_args


@pytest.fixture(autouse=True)
def _disable_prettier_for_skill_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """These generation tests assert content, not Prettier integration."""

    monkeypatch.setattr(init_skills_handler, "_prettier_available", lambda: False)


@pytest.mark.parametrize(
    ("skill_name", "expected_phrases"),
    [
        (
            "sase_artifact_file",
            (
                "sase artifact create -p",
                "--kind",
                "--move",
                "sase artifact list",
                "sase artifact show",
                "sase artifact path",
                "sase artifact open",
                "sase artifact doctor",
                'sase artifact create -p <path> -l "<label>" --bead',
            ),
        ),
        (
            "sase_agents_status",
            (
                "sase agent list -j",
                "sase agent show <name>",
                "artifacts_dir",
                "cite the artifact paths",
            ),
        ),
        (
            "sase_chats",
            (
                "sase chat list -j",
                "sase chat show",
                "/sase_agents_status",
                "draft/live",
            ),
        ),
        (
            "sase_gate",
            (
                "beautiful, robust, and powerful custom notification gates",
                "dangerous or irreversible command",
                '"query": "(restart AND verify) OR reject"',
                '"default_selected": true',
                '"feedback": "required"',
                '"groups": [',
                '"panel": "deployments"',
                '"panel_icon": "🚀"',
                "`presentation.origin_agent`",
                "sase gate create",
                "sase gate wait",
                "selected_option_ids",
                "Never poll bundle files directly",
                "Never run bundle commands by hand",
                "Automatic resolution is forbidden for custom gates",
            ),
        ),
        (
            "sase_changespecs",
            (
                "Compatibility reference for the legacy `/sase_changespecs` skill",
                "Use `/sase_patches` for normal Patch work",
                "sase changespec current -f markdown",
            ),
        ),
        (
            "sase_patches",
            (
                "sase patch current -f markdown",
                "sase patch search '<query>' -f markdown",
                "Patches can carry a `REFS:` section",
                "sase patch ref add --patch <name>",
                "project.patch_refs",
            ),
        ),
        (
            "sase_memory_read",
            (
                "sase memory read",
                "--reason",
                "## Children",
            ),
        ),
        (
            "sase_pipe",
            (
                "sase pipe 'implement the approved plan'",
                "--reason 'hand off to a coding pass' --model opus",
                "kills the calling agent once it starts the hand-off",
                "this turn will not return normally",
                "Do not pipe for",
                "use `/sase_monitor` instead",
                "use `/sase_run` instead",
                "-f, --fresh",
                "-m, --model MODEL",
                "-n, --name TOKEN",
                "The piped prompt is re-parsed by the successor",
                "max_agent_pipe_chain",
                "Do not keep working, poll, or wait after running this command",
            ),
        ),
        (
            "sase_monitor",
            (
                "sase monitor start",
                "kills the current agent",
                "The current provider turn will not return normally",
                "Do not poll",
                "--command 'just check-full'",
                "--timeout 45m",
                "--start-status TESTING",
                "--stop-status TESTED",
                "--next 'Fix anything just check-full reported",
                "--command 'sleep 300'",
                "--start-status 'SLEEPING FOR 300s'",
                "--stop-status 'SLEPT FOR 300s'",
                "Both `-s/--start-status` and `-S/--stop-status` are required",
                "present tense",
                "past tense",
                "20 characters",
                "--start-status COLLECTING",
                "--stop-status COLLECTED",
                "Omit `--next`",
                "sase monitor list",
                "--all",
                "sase monitor show <id>",
                "--follow",
                "sase monitor stop <id>",
                "do not launch their recorded follow-up agent",
                "previous conversation through `#fork`",
                "path to the retained captured log",
                "--idle-timeout DURATION",
                "--next-output none|tail|file",
                "`--reason` and `--next` text reaches the follow-up literally",
                "If the command fails or times out, the follow-up still launches",
            ),
        ),
        (
            "sase_new_task",
            (
                "sase memory read sase_beads.md",
                "sase memory read sase_sizes.md",
                "sase bead search "
                "'symbol|filename|command|error-fragment' --regex --type task",
                "sase bead +1 <task-id>",
                "Do not create a task",
                "same underlying defect/root cause or desired remediation",
                "retired umbrella",
                "forbids `+1`",
                "Do not `+1` or reopen them",
                "node-specific task bead named for the failing node ID",
                "sase bead list --type task --since 1w --status all",
                "created in the last week",
                "sase bead list --type plan --tier epic --status in_progress",
                "DISCOVERED ISSUE:",
                "If both the duplicate and active-epic branches apply, record both",
                'sase bead create -T "task(<slug>)"',
                "RELATED:",
                "--size <size>",
                "Default to\n   `large`",
            ),
        ),
        (
            "sase_notify",
            (
                "sase notify list -j",
                "sase notify show --id",
                "interaction_requests/<kind>/<request-id>/request.json",
                "sase gate create",
                "sase gate wait",
                "CustomGate",
                "/sase_gate",
                '"silent": true',
            ),
        ),
        (
            "sase_plan",
            (
                "sase memory read sase_sizes.md",
                "Use `tale`",
                "Use `epic`",
                "unique slug ID",
                "Authoring a tale plan is `large` work",
                "`tier: <tier>`",
                "`<tier>` is either `tale` or `epic`",
                "Tale frontmatter must declare `size: xsmall | small | medium`",
                "sase plan validate sase_plan_<name>.md --explain",
                "sase plan validate sase_plan_<name>.md",
                "expected schema and all diagnostics",
                "Do not propose a plan that has not passed validation",
                "sase plan propose sase_plan_<name>.md",
                "writes a handoff marker",
                "do not poll response files yourself",
            ),
        ),
        (
            "sase_questions",
            (
                "sase questions '<json>'",
                "writes a durable handoff marker",
                "sends `SIGTERM`",
                "Do not poll question request or response files",
            ),
        ),
        (
            "sase_project",
            (
                "sase project list --json",
                "effective_project_name",
                "sase project current",
                "sase project set-current <project>",
                "sase project disable <project>",
                "sase project alias list",
                "/sase_run",
                "/sase_repo",
            ),
        ),
        (
            "sase_repo",
            (
                "sase repo open sase-github",
                "sase repo open dotdrop",
                "sase repo open gh:pallets/click",
                "sase repo open gh:steveyegge/beads",
                "Use that printed path as the only path",
                "Do not web-fetch",
                "raw.githubusercontent.com",
                "GitHub issue and PR discussions",
                "sase repo list",
                "sase repo log",
            ),
        ),
        (
            "sase_run",
            (
                "sase launch request",
                '"status": "approved"',
                '"selected_option_ids": ["approve"]',
                "do not poll request files yourself",
                "%i(reviewer, family=parent)",
                "Do not run `sase run`",
                "#git:home",
                "%w(",
                "sase xprompt list",
                "%xprompts_enabled:false",
                "sase xprompt expand",
                "max_slots_exceeded",
                "interaction_requests/launch/<request-id>/",
            ),
        ),
        (
            "sase_var",
            (
                "sase var set KEY=VALUE",
                "sase var get --format json",
                "sase var get '<build>'",
                "sase var list",
                "1,024 total nodes",
                "Map keys are stored and displayed in sorted order",
                "%id:build-@",
                '{{ agents["build"].result_path }}',
                "Telegram completion message",
                "sase var set STOP=1",
                "only affects later `%repeat` / `%r` slots",
            ),
        ),
    ],
)
def test_shipped_skill_source_is_discoverable_for_all_skill_providers(
    skill_name: str,
    expected_phrases: tuple[str, ...],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shipped ``skill: true`` sources render to every deployable provider."""
    src = get_sase_package_skills_dir() / f"{skill_name}.md"
    assert src.is_file(), f"missing skill source: {src}"

    front_matter, body = parse_yaml_front_matter(src.read_text(encoding="utf-8"))
    assert front_matter is not None
    assert front_matter.get("name") == skill_name
    assert front_matter.get("skill") is True
    assert front_matter.get("description")
    assert body.strip(), "skill body must not be empty"
    # Compare on collapsed whitespace: prose phrases straddle line breaks that
    # move whenever the Markdown prose width changes.
    flat_body = collapse_whitespace(body)
    for phrase in expected_phrases:
        assert collapse_whitespace(phrase) in flat_body

    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(make_args())
    assert exc.value.code == 0

    providers = get_skill_target_providers(True)
    assert providers, "expected at least one registered llm provider"

    for provider in providers:
        target = _get_target_path(provider, skill_name, use_chezmoi=False)
        assert target.exists(), f"{skill_name} not generated for provider {provider}"
        rendered = collapse_whitespace(target.read_text(encoding="utf-8"))
        for phrase in expected_phrases:
            assert collapse_whitespace(phrase) in rendered
