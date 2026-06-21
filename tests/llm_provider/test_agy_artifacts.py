"""AgyProvider fake-CLI artifact and argv transport tests."""

import textwrap
from pathlib import Path

import pytest

from sase.llm_provider.agy import AgyProvider


def test_agy_provider_invokes_fake_cli_and_writes_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_agy = tmp_path / "agy"
    fake_agy.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import sys

            argv = sys.argv
            if "--print-timeout" not in argv or "--model" not in argv:
                sys.stderr.write("missing required flags\\n")
                sys.exit(64)
            if "--dangerously-skip-permissions" not in argv:
                sys.stderr.write("missing skip-permissions\\n")
                sys.exit(64)
            if argv[-2] != "--print":
                sys.stderr.write(f"prompt not behind --print: {argv!r}\\n")
                sys.exit(64)
            if "SASE Antigravity print-mode instructions" not in argv[-1]:
                sys.stderr.write("missing print-mode directive\\n")
                sys.exit(64)
            if "Run commands synchronously" not in argv[-1]:
                sys.stderr.write("missing sync-command directive\\n")
                sys.exit(64)
            if "--- User Prompt ---\\nfake agy prompt" not in argv[-1]:
                sys.stderr.write(f"unexpected prompt argv: {argv[-1]!r}\\n")
                sys.exit(64)

            print("agy fake ok", flush=True)
            """
        )
    )
    fake_agy.chmod(0o755)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_AGY_PATH", str(fake_agy))
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))

    result = AgyProvider().invoke(
        "fake agy prompt", model_tier="large", suppress_output=True
    )

    assert result.content == "agy fake ok"
    # No stable token accounting in plain-stdout mode.
    assert result.usage is None
    assert (artifacts / "live_reply.md").read_text().strip() == "agy fake ok"


def test_agy_provider_writes_live_reply_but_no_structured_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plain stdout must never be scraped into fake structured artifacts.

    ``agy`` writes ``live_reply.md`` like every other provider, and the guarded
    trajectory extractor may write tool rows for supported versions. Human
    stdout display text must still never be fabricated into ``tool_calls.jsonl``,
    ``usage.json``, or thinking rows.
    """
    fake_agy = tmp_path / "agy"
    # A reply whose prose looks tool-shaped (glyphs, "Running"/"tool" words)
    # must NOT be scraped into a structured tool-call artifact.
    fake_agy.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            print("● Running tool: Bash(echo hi)", flush=True)
            print("final agy answer", flush=True)
            """
        )
    )
    fake_agy.chmod(0o755)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_AGY_PATH", str(fake_agy))
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))

    result = AgyProvider().invoke("do work", model_tier="large", suppress_output=True)

    # The plain-stdout reply is captured verbatim, including tool-shaped prose.
    assert "final agy answer" in result.content
    assert "Running tool" in result.content
    # No stable token accounting in plain-stdout mode: do not lie about usage.
    assert result.usage is None

    # live_reply.md is the supported MVP artifact and is written.
    live_reply = artifacts / "live_reply.md"
    assert live_reply.is_file()
    assert "final agy answer" in live_reply.read_text(encoding="utf-8")

    # No malformed / fabricated structured artifacts are created.
    assert not (artifacts / "tool_calls.jsonl").exists()
    assert not (artifacts / "usage.json").exists()
    assert not (artifacts / "codex_thinking.jsonl").exists()


def test_agy_provider_fake_cli_no_shell_interpolation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A prompt full of shell-significant characters must reach the CLI as a
    # single, untouched argv element (proving subprocess uses an argv list,
    # not a shell string).
    tricky_prompt = "he said \"hi\"; rm -rf /\nline two\twith 'quotes' & $(echo no)"
    expected_file = tmp_path / "expected_prompt.txt"
    expected_file.write_text(tricky_prompt, encoding="utf-8")

    fake_agy = tmp_path / "agy"
    fake_agy.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import os
            import sys

            expected = open(os.environ["EXPECTED_PROMPT_FILE"], encoding="utf-8").read()
            if expected not in sys.argv[-1]:
                sys.stderr.write(f"prompt was mangled: {sys.argv[-1]!r}\\n")
                sys.exit(65)
            if "SASE Antigravity print-mode instructions" not in sys.argv[-1]:
                sys.stderr.write("prompt directive missing\\n")
                sys.exit(65)
            print("no interpolation", flush=True)
            """
        )
    )
    fake_agy.chmod(0o755)
    monkeypatch.setenv("SASE_AGY_PATH", str(fake_agy))
    monkeypatch.setenv("EXPECTED_PROMPT_FILE", str(expected_file))

    result = AgyProvider().invoke(
        tricky_prompt, model_tier="large", suppress_output=True
    )

    assert result.content == "no interpolation"
