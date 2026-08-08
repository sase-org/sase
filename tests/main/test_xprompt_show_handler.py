"""End-to-end handler tests for ``sase xprompt show``."""

from __future__ import annotations

from dataclasses import replace
import json

import pytest

from sase.main.parser import create_parser
from sase.main.xprompt_handler import handle_xprompt_command
from sase.xprompt.cli_show_model import ShowProvenance, XPromptShowRecord
from sase.xprompt.cli_show_resolve import ShowLookupMiss


def _record(**overrides: object) -> XPromptShowRecord:
    base = XPromptShowRecord(
        name="demo",
        reference="#demo",
        prefix="#",
        kind="xprompt",
        is_skill=False,
        skill_name=None,
        is_swarm=False,
        segment_count=1,
        description="Demo prompt.",
        project="sase",
        provenance=ShowProvenance(
            source_id="project:demo",
            source_bucket="project",
            source_display="sase/xprompts/demo.md",
            definition_path="/work/sase/xprompts/demo.md",
            definition_line=1,
            hosted_url=None,
            editable=True,
        ),
        tags=[],
        skill=None,
        snippet=None,
        log_skill_use=None,
        input_signature=None,
        inputs=[],
        local_xprompts=[],
        steps=[],
        body="#demo body",
        body_first_line=1,
        raw="exact\nbytes",
        warnings=[],
        references=[],
    )
    return replace(base, **overrides)


def _dispatch(argv: list[str]) -> int:
    args = create_parser().parse_args(["xprompt", *argv])
    with pytest.raises(SystemExit) as exc_info:
        handle_xprompt_command(args)
    return int(exc_info.value.code)


def test_show_full_hit_renders_without_color_when_disabled(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.xprompt.cli_show as cli_show

    monkeypatch.setattr(cli_show, "resolve_show_record", lambda *_a, **_k: _record())

    assert _dispatch(["show", "demo", "--color", "never"]) == 0

    captured = capsys.readouterr()
    assert "#demo" in captured.out
    assert "Demo prompt." in captured.out
    assert "\x1b" not in captured.out
    assert captured.err == ""


def test_show_miss_exits_one_with_suggestions(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.xprompt.cli_show as cli_show

    monkeypatch.setattr(
        cli_show,
        "resolve_show_record",
        lambda *_a, **_k: ShowLookupMiss("syn", ["#!sync"]),
    )

    assert _dispatch(["show", "syn"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unknown xprompt: syn" in captured.err
    assert "#!sync" in captured.err


def test_show_json_outputs_parseable_schema_and_stderr_warnings(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.xprompt.cli_show as cli_show

    monkeypatch.setattr(
        cli_show,
        "resolve_show_record",
        lambda *_a, **_k: _record(warnings=["arguments ignored"]),
    )

    assert _dispatch(["show", "#demo(arg)", "--format", "json"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["schema_version"] == 1
    assert payload["name"] == "demo"
    assert captured.err == "arguments ignored\n"


def test_show_raw_outputs_exact_definition_without_added_newline(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.xprompt.cli_show as cli_show

    monkeypatch.setattr(
        cli_show,
        "resolve_show_record",
        lambda *_a, **_k: _record(raw="exact bytes"),
    )

    assert _dispatch(["show", "demo", "--format", "raw"]) == 0

    captured = capsys.readouterr()
    assert captured.out == "exact bytes"
    assert captured.err == ""


def test_show_raw_unavailable_exits_two_and_keeps_stdout_clean(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.xprompt.cli_show as cli_show

    monkeypatch.setattr(
        cli_show,
        "resolve_show_record",
        lambda *_a, **_k: _record(raw=None, warnings=["raw warning"]),
    )

    assert _dispatch(["show", "demo", "--format", "raw"]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "raw warning" in captured.err
    assert "raw definition unavailable for #demo" in captured.err
