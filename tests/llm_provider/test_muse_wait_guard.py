"""Muse provider stranded-wait guard tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.llm_provider._wait_signals import WAIT_SIGNAL_RE, ends_with_wait_claim
from sase.llm_provider.muse import (
    _MUSE_WAIT_CONTINUATION_NUDGE,
    _muse_max_wait_continuations,
    MuseProvider,
)
from sase.llm_provider.types import LLMInvocationError


def _usage() -> dict[str, int]:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }


def _invoke_with_replies(
    replies: list[tuple[str, str, int]],
) -> tuple[object, list[str]]:
    """Invoke a MuseProvider against canned subprocess replies.

    Returns the result (or raised error is propagated) and every prompt file's
    contents in cycle order.
    """
    provider = MuseProvider()
    prompts: list[str] = []
    calls = {"n": 0}

    def _fake_run(
        args: list[str],
        suppress_output: bool,
        session_id: str | None = None,
    ) -> tuple[str, str, int, dict[str, int]]:
        del suppress_output, session_id
        prompt_file = Path(args[args.index("--prompt-file") + 1])
        prompts.append(prompt_file.read_text(encoding="utf-8"))
        content, stderr, return_code = replies[calls["n"]]
        calls["n"] += 1
        return (content, stderr, return_code, _usage())

    with (
        patch("sase.llm_provider.muse.provider_timer"),
        patch.object(MuseProvider, "_run_subprocess", side_effect=_fake_run),
    ):
        result = provider.invoke(
            "original task", model_tier="large", suppress_output=True
        )
    return result, prompts


def test_muse_wait_claim_triggers_one_continuation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_MUSE_MAX_WAIT_CONTINUATIONS", raising=False)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)

    result, prompts = _invoke_with_replies(
        [
            ("Started the check; I'll wait for it to finish.", "", 0),
            ("All done.", "", 0),
        ]
    )

    assert result.content == (
        "Started the check; I'll wait for it to finish.\n\nAll done."
    )
    assert len(prompts) == 2
    assert prompts[0].endswith("\n\n--- User Prompt ---\noriginal task")
    assert "--- Work So Far ---\nStarted the check;" in prompts[1]
    assert (
        f"--- Required Continuation ---\n{_MUSE_WAIT_CONTINUATION_NUDGE}"
        in (prompts[1])
    )
    # The reconstructed continuation keeps the single-turn directive.
    assert prompts[1].startswith("SASE single-turn instructions for Muse Code")
    assert "--- User Prompt ---\noriginal task\n\n--- Work So Far ---" in prompts[1]


def test_muse_wait_guard_budget_exhaustion_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_MUSE_MAX_WAIT_CONTINUATIONS", "1")
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    provider = MuseProvider()
    calls = {"n": 0}

    def _fake_run(
        args: list[str],
        suppress_output: bool,
        session_id: str | None = None,
    ) -> tuple[str, str, int, dict[str, int]]:
        del args, suppress_output, session_id
        calls["n"] += 1
        return ("Still running, so I'll wait.", "", 0, _usage())

    with (
        patch("sase.llm_provider.muse.provider_timer"),
        patch.object(MuseProvider, "_run_subprocess", side_effect=_fake_run),
        pytest.raises(LLMInvocationError) as exc_info,
    ):
        provider.invoke("run it", model_tier="large", suppress_output=True)

    # One initial run plus one budgeted continuation, then the loud failure.
    assert calls["n"] == 2
    message = str(exc_info.value)
    assert "wait-claim reply" in message
    assert "stranded_wait_claim" in message


def test_muse_wait_guard_zero_budget_raises_without_continuation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_MUSE_MAX_WAIT_CONTINUATIONS", "0")
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    provider = MuseProvider()
    calls = {"n": 0}

    def _fake_run(
        args: list[str],
        suppress_output: bool,
        session_id: str | None = None,
    ) -> tuple[str, str, int, dict[str, int]]:
        del args, suppress_output, session_id
        calls["n"] += 1
        return ("I'll wait for the command.", "", 0, _usage())

    with (
        patch("sase.llm_provider.muse.provider_timer"),
        patch.object(MuseProvider, "_run_subprocess", side_effect=_fake_run),
        pytest.raises(LLMInvocationError),
    ):
        provider.invoke("run it", model_tier="large", suppress_output=True)

    assert calls["n"] == 1


def test_muse_clean_answer_does_not_continue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_MUSE_MAX_WAIT_CONTINUATIONS", raising=False)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)

    result, prompts = _invoke_with_replies([("All done.", "", 0)])

    assert result.content == "All done."
    assert len(prompts) == 1


def test_muse_wait_guard_names_artifacts_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_MUSE_MAX_WAIT_CONTINUATIONS", "0")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    provider = MuseProvider()

    def _fake_run(
        args: list[str],
        suppress_output: bool,
        session_id: str | None = None,
    ) -> tuple[str, str, int, dict[str, int]]:
        del args, suppress_output, session_id
        return ("I'll wait for the command.", "", 0, _usage())

    with (
        patch("sase.llm_provider.muse.provider_timer"),
        patch.object(MuseProvider, "_run_subprocess", side_effect=_fake_run),
        pytest.raises(LLMInvocationError) as exc_info,
    ):
        provider.invoke("run it", model_tier="large", suppress_output=True)

    assert str(tmp_path) in str(exc_info.value)


def test_muse_wait_guard_logs_each_firing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SASE_MUSE_MAX_WAIT_CONTINUATIONS", raising=False)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))

    _invoke_with_replies(
        [
            ("Started it; still running so I'll wait.", "", 0),
            ("All done.", "", 0),
        ]
    )

    entries = [
        json.loads(line)
        for line in (tmp_path / "wait_guard_log.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert len(entries) == 1
    assert entries[0]["reason"] == "stranded_wait_claim"
    assert entries[0]["cycle"] == 1
    assert isinstance(entries[0]["timestamp"], float)


def test_muse_interrupt_takes_precedence_over_wait_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_MUSE_MAX_WAIT_CONTINUATIONS", raising=False)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    provider = MuseProvider()
    prompts: list[str] = []
    calls = {"n": 0}

    def _fake_run(
        args: list[str],
        suppress_output: bool,
        session_id: str | None = None,
    ) -> tuple[str, str, int, dict[str, int]]:
        del suppress_output, session_id
        prompt_file = Path(args[args.index("--prompt-file") + 1])
        prompts.append(prompt_file.read_text(encoding="utf-8"))
        calls["n"] += 1
        if calls["n"] == 1:
            provider._pending_interrupt_message = "also update the README"
            return ("First pass; I'll wait for the rest.", "", 0, _usage())
        return ("Second pass.", "", 0, _usage())

    with (
        patch("sase.llm_provider.muse.provider_timer"),
        patch.object(MuseProvider, "_run_subprocess", side_effect=_fake_run),
    ):
        result = provider.invoke(
            "original task", model_tier="large", suppress_output=True
        )

    assert result.content == "First pass; I'll wait for the rest.\n\nSecond pass."
    assert "--- User Message ---\nalso update the README" in prompts[1]
    assert "--- Required Continuation ---" not in prompts[1]


@pytest.mark.parametrize(
    ("env_value", "expected"),
    [
        (None, 2),
        ("0", 0),
        ("3", 3),
        ("garbage", 2),
        ("", 2),
    ],
)
def test_muse_wait_budget_parses(
    monkeypatch: pytest.MonkeyPatch, env_value: str | None, expected: int
) -> None:
    if env_value is None:
        monkeypatch.delenv("SASE_MUSE_MAX_WAIT_CONTINUATIONS", raising=False)
    else:
        monkeypatch.setenv("SASE_MUSE_MAX_WAIT_CONTINUATIONS", env_value)
    assert _muse_max_wait_continuations() == expected


def test_muse_negative_wait_budget_clamps_to_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_MUSE_MAX_WAIT_CONTINUATIONS", "-2")
    assert _muse_max_wait_continuations() == 0


@pytest.mark.parametrize(
    "tail",
    [
        "...so I'll wait.",
        "The command is still running.",
        "Running in the background, will notify when it completes.",
    ],
)
def test_shared_wait_signal_matches_wait_claims(tail: str) -> None:
    assert ends_with_wait_claim(tail) is True
    assert ends_with_wait_claim(f"Done.\n\n{tail}") is True


def test_shared_wait_signal_ignores_complete_answers() -> None:
    assert (
        ends_with_wait_claim(
            "Implemented the fix and verified the provider tests passed."
        )
        is False
    )


def test_shared_wait_signal_only_reads_the_tail() -> None:
    assert ends_with_wait_claim("I'll wait for it. " + ("x" * 800)) is False


def test_claude_and_muse_share_one_wait_signal_pattern() -> None:
    from sase.llm_provider import claude as claude_module

    assert claude_module.ends_with_wait_claim is ends_with_wait_claim
    assert WAIT_SIGNAL_RE.pattern
