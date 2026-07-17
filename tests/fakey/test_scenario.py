from __future__ import annotations

from pathlib import Path

import pytest

from sase.fakey.scenario import (
    DEFAULT_REPLY,
    ScenarioError,
    resolve_scenario,
    select_attempt,
)


def test_default_scenario_succeeds_with_canned_reply(tmp_path: Path) -> None:
    resolved = resolve_scenario("hello", env={"FAKEY_STATE_DIR": str(tmp_path)})

    assert resolved.data["reply"] == DEFAULT_REPLY
    assert resolved.data["delay"] == 0.0
    assert "attempts" not in resolved.data


def test_demo_scenario_is_long_streaming_and_prompt_separator_safe(
    tmp_path: Path,
) -> None:
    resolved = resolve_scenario(
        "demo prompt",
        env={
            "FAKEY_SCENARIO": "@demo",
            "FAKEY_STATE_DIR": str(tmp_path),
        },
    )

    lines = resolved.data["reply"].splitlines()
    assert resolved.source == "@demo"
    assert resolved.data["delay"] == 2
    assert resolved.data["stream"]["chunk_delay"] == 1
    assert len(lines) >= 40
    assert "---" not in lines


def test_layers_env_then_file_then_prompt(tmp_path: Path) -> None:
    scenario = tmp_path / "scenario.yml"
    scenario.write_text("reply: from file\ndelay: 0.2\n")
    prompt = """hello
```fakey
reply: from prompt
```
"""

    resolved = resolve_scenario(
        prompt,
        env={
            "FAKEY_DELAY": "0.1",
            "FAKEY_REPLY": "from env",
            "FAKEY_SCENARIO": str(scenario),
            "FAKEY_STATE_DIR": str(tmp_path / "state"),
        },
    )

    assert resolved.data["reply"] == "from prompt"
    assert resolved.data["delay"] == 0.2
    assert resolved.source.startswith("prompt:")


def test_explicit_selector_overrides_env_selector(tmp_path: Path) -> None:
    env_scenario = tmp_path / "env.yml"
    env_scenario.write_text("reply: env scenario\n")
    explicit_scenario = tmp_path / "explicit.yml"
    explicit_scenario.write_text("reply: explicit scenario\n")

    resolved = resolve_scenario(
        "",
        selector=str(explicit_scenario),
        env={"FAKEY_SCENARIO": str(env_scenario)},
    )

    assert resolved.data["reply"] == "explicit scenario"


def test_fail_times_builds_a_sequence_that_ends_in_success(tmp_path: Path) -> None:
    resolved = resolve_scenario(
        "",
        env={
            "FAKEY_FAIL_MESSAGE": "busy",
            "FAKEY_FAIL_TIMES": "2",
            "FAKEY_REPLY": "ready",
            "FAKEY_STATE_DIR": str(tmp_path),
        },
    )

    assert select_attempt(resolved.data, 0)["fail"]["message"] == "busy"
    assert select_attempt(resolved.data, 1)["fail"]["retryable"] is True
    assert select_attempt(resolved.data, 2)["reply"] == "ready"
    assert select_attempt(resolved.data, 99)["reply"] == "ready"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("version: 2\n", "version must be 1"),
        ("attempts: []\n", "attempts must be a non-empty list"),
        ("delay: soon\n", "delay must be a number"),
        ("mystery: true\n", "unknown"),
        ("steps:\n  - teleport: /tmp/x\n", "unknown step"),
        (
            "attempts:\n  - fail: {message: no}\n    succeed: true\n",
            "both fail and succeed",
        ),
    ],
)
def test_validation_errors_are_actionable(
    tmp_path: Path, text: str, message: str
) -> None:
    scenario = tmp_path / "bad.yml"
    scenario.write_text(text)

    with pytest.raises(ScenarioError, match=message):
        resolve_scenario("", selector=str(scenario), env={})


def test_multiple_prompt_blocks_are_rejected() -> None:
    prompt = "```fakey\nreply: one\n```\n```fakey\nreply: two\n```"

    with pytest.raises(ScenarioError, match="more than one"):
        resolve_scenario(prompt, env={})


def test_scenario_file_defaults_state_alongside_file(tmp_path: Path) -> None:
    scenario = tmp_path / "case.yml"
    scenario.write_text("reply: ok\n")

    resolved = resolve_scenario("", selector=str(scenario), env={})

    assert resolved.state_dir == tmp_path
