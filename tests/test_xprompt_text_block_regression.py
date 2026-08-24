"""Launch-level [[...]] text-block regression coverage and shared corpus."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.agent.multi_prompt_reference_directives import extract_static_clan_directive
from sase.agent.xprompt_swarm import expand_xprompt_swarms_with_metadata
from sase.xprompt._parsing import iter_xprompt_references, parse_args
from sase.xprompt.directives import extract_prompt_directives
from sase.xprompt.models import InputArg, InputType, XPrompt
from sase.xprompt.processor import process_xprompt_references
from sase.xprompt.unresolved import scan_query_for_unresolved_references

from tests._xprompt_swarm_helpers import patch_catalog, xp

_CORPUS_PATH = Path(__file__).resolve().parent / "fixtures" / "xprompt_args_corpus.json"
_CORE_CORPUS_RELATIVE = (
    Path("crates") / "sase_core" / "tests" / "fixtures" / "xprompt_args_corpus.json"
)

_FIXTURE_NAME = "research_fixture"
_PROSE = (
    "Use `[<web>:<keyword> [...]]` for example, then keep this comma, "
    "and compare C++ with Rust."
)


def _load_corpus() -> dict[str, Any]:
    payload = json.loads(_CORPUS_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["cases"]
    return payload


def _corpus_cases() -> list[dict[str, Any]]:
    return list(_load_corpus()["cases"])


def _core_corpus_candidates() -> list[Path]:
    repo_root = Path(__file__).resolve().parents[1]
    return [
        repo_root / "sase" / "repos" / "linked" / "sase-core" / _CORE_CORPUS_RELATIVE,
        repo_root.parent / "sase-core" / _CORE_CORPUS_RELATIVE,
    ]


def _fixture_xprompt() -> XPrompt:
    return xp(
        _FIXTURE_NAME,
        "%clan(research.fixture, tribe=research,\n"
        "summary=[[[bold]RESEARCH PROMPT:[/bold] {{ prompt }}]]) "
        "%id:research.fixture.cdx\n"
        "{{ prompt }}\n"
        "---\n"
        "follow-up {{ prompt }}",
        inputs=[
            InputArg(name="prompt", type=InputType.TEXT),
            InputArg(name="wait", type=InputType.WORD, default=None),
            InputArg(name="priority", type=InputType.INT, default=None),
        ],
    )


def _query() -> str:
    return f"#{_FIXTURE_NAME}:: {_PROSE}"


@pytest.mark.parametrize("case", _corpus_cases(), ids=lambda case: str(case["id"]))
def test_shared_corpus_parse_args(case: dict[str, Any]) -> None:
    """Python parse_args matches the shared cross-language corpus."""
    positional, named = parse_args(str(case["source"]))

    assert positional == case["positional"]
    assert named == case["named"]


def test_shared_corpus_matches_sase_core_copy() -> None:
    """Keep the sase and sase-core corpus copies from drifting silently."""
    matches = [path for path in _core_corpus_candidates() if path.is_file()]
    if not matches:
        pytest.skip("sase-core checkout with xprompt args corpus is not available")

    expected = _CORPUS_PATH.read_bytes()
    for path in matches:
        assert path.read_bytes() == expected, path


def test_double_colon_swarm_prose_binds_one_positional_without_text_block_leak() -> (
    None
):
    """The failing `#name:: prose with ]] and commas` shape binds as one value."""
    query = _query()
    refs = iter_xprompt_references(query)

    assert len(refs) == 1
    positional, named = refs[0].parse_arguments()
    assert named == {}
    assert positional == [_PROSE]
    assert not positional[0].startswith("[[")
    assert "]]" in positional[0]


def test_double_colon_swarm_clan_summary_survives_inner_marker() -> None:
    """Launch expansion interpolates the payload into `%clan(..., summary=[[...]])`."""
    catalog = {_FIXTURE_NAME: _fixture_xprompt()}
    query = _query()

    with patch_catalog(catalog):
        records = expand_xprompt_swarms_with_metadata([query])

    assert len(records) == 2
    first = records[0].prompt
    static = extract_static_clan_directive(first)
    cleaned, directives = extract_prompt_directives(first)

    assert static is not None
    assert static.name == "research.fixture"
    assert static.tribe == "research"
    assert directives.clan == "research.fixture"
    assert directives.clan_tribe == "research"
    assert directives.clan_summary is not None
    assert _PROSE in directives.clan_summary
    assert _PROSE in cleaned
    assert "follow-up" in records[1].prompt


def test_launch_pre_scan_emits_nothing_for_inner_marker_prose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The launch unresolved-reference pre-scan stays silent on the failing shape."""
    fixture = _fixture_xprompt()
    catalog = {_FIXTURE_NAME: fixture}
    monkeypatch.setattr(
        "sase.xprompt.processor.get_all_xprompts",
        lambda *args, **kwargs: catalog,
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_prompts",
        lambda *args, **kwargs: catalog,
    )

    query = _query()
    expanded = process_xprompt_references(query, raise_on_error=True)
    assert _PROSE in expanded
    assert "]]" in expanded

    with patch("sase.xprompt.processor.print_status") as print_status:
        unresolved = scan_query_for_unresolved_references(query)

    assert unresolved == ()
    print_status.assert_not_called()
