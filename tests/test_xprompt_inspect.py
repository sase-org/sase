"""Tests for frontend-agnostic xprompt syntax span inspection."""

from __future__ import annotations

from sase.xprompt import xprompt_inspect
from sase.xprompt.xprompt_inspect import XPromptSpan


def _source_by_kind(
    text: str,
    kind: str,
    *,
    known_skills: frozenset[str] = frozenset(),
) -> list[str]:
    return [
        text[span.start : span.end]
        for span in xprompt_inspect.tokenize(text, known_skills=known_skills)
        if span.kind == kind
    ]


def test_tokenize_empty_and_marker_free_text() -> None:
    assert xprompt_inspect.tokenize("") == []
    assert xprompt_inspect.tokenize("ordinary prompt text") == []


def test_tokenize_all_invocation_argument_forms() -> None:
    text = (
        "#foo #!bar #ns/name #args(a, k=v) #colon:value "
        "#quoted:`two words` #plus+ #ask!! #skip??\n"
        "#short: text until blank\ncontinues\n\n"
        "#double:: one line\nnext"
    )

    assert _source_by_kind(text, "invocation") == [
        "#foo",
        "#!bar",
        "#ns/name",
        "#args",
        "#colon",
        "#quoted",
        "#plus",
        "#ask!!",
        "#skip??",
        "#short",
        "#double",
    ]
    assert _source_by_kind(text, "invocation_arg") == [
        "(a, k=v)",
        ":value",
        ":`two words`",
        "+",
        ": text until blank\ncontinues",
        ":: one line\nnext",
    ]


def test_tokenize_known_directives_aliases_and_arguments_only() -> None:
    text = "%wait:x %w %model(opus) %m:sonnet %clan:root %c:root %auto %notadirective"

    assert _source_by_kind(text, "directive") == [
        "%wait",
        "%w",
        "%model",
        "%m",
        "%clan",
        "%c",
        "%auto",
    ]
    assert _source_by_kind(text, "directive_arg") == [
        ":x",
        "(opus)",
        ":sonnet",
        ":root",
        ":root",
    ]


def test_tokenize_segment_separators_only_on_standalone_lines() -> None:
    text = "before --- after\n---\n  ---  \n----"

    assert _source_by_kind(text, "separator") == ["---"]


def test_tokenize_skips_fences_and_disabled_regions() -> None:
    text = (
        "```text\n#fenced %wait:fenced\n---\n```\n"
        "%xprompts_enabled:false\n#disabled %m:disabled\n---\n"
        "%xprompts_enabled:true\n"
        "#active %wait:active\n---"
    )

    assert _source_by_kind(text, "invocation") == ["#active"]
    assert _source_by_kind(text, "invocation_arg") == []
    assert _source_by_kind(text, "directive") == ["%wait"]
    assert _source_by_kind(text, "directive_arg") == [":active"]
    assert _source_by_kind(text, "separator") == ["---"]


def test_tokenize_skips_every_overlay_kind_inside_inline_code() -> None:
    text = "`#hidden:arg %m:opus --- /sase_plan` #active:arg %m:sonnet /sase_plan"
    known = frozenset({"sase_plan"})

    assert _source_by_kind(text, "invocation", known_skills=known) == ["#active"]
    assert _source_by_kind(text, "invocation_arg", known_skills=known) == [":arg"]
    assert _source_by_kind(text, "directive", known_skills=known) == ["%m"]
    assert _source_by_kind(text, "directive_arg", known_skills=known) == [":sonnet"]
    assert _source_by_kind(text, "separator", known_skills=known) == []
    assert _source_by_kind(text, "skill", known_skills=known) == ["/sase_plan"]


def test_tokenize_rejects_heading_and_midword_markers() -> None:
    text = "# Heading\nword#foo word%wait"

    assert xprompt_inspect.tokenize(text) == []


def test_tokenize_uses_character_offsets_for_multibyte_text() -> None:
    text = "café #foo:value %m:opus"
    spans = xprompt_inspect.tokenize(text)

    assert spans[0] == XPromptSpan(5, 9, "invocation")
    assert text[spans[1].start : spans[1].end] == ":value"
    assert text[spans[2].start : spans[2].end] == "%m"


def test_tokenize_handles_guard_limit_sized_input() -> None:
    text = ("plain text " * 7_000)[:79_950] + "\n#final %auto"

    assert _source_by_kind(text, "invocation") == ["#final"]
    assert _source_by_kind(text, "directive") == ["%auto"]


def test_tokenize_known_slash_skills_only() -> None:
    text = "use /sase_plan, then (/sase_repo) and '/sase_git_commit'"
    known = frozenset({"sase_plan", "sase_repo", "sase_git_commit"})

    assert _source_by_kind(text, "skill", known_skills=known) == [
        "/sase_plan",
        "/sase_repo",
        "/sase_git_commit",
    ]


def test_tokenize_rejects_unknown_greedy_and_path_like_slash_references() -> None:
    text = (
        "/foo /sase_planner research/sase_plan https://x/sase_plan "
        "/sase_plan/child /sase_plan-extra /sase_plan.md"
    )

    assert (
        _source_by_kind(
            text,
            "skill",
            known_skills=frozenset({"sase_plan"}),
        )
        == []
    )


def test_tokenize_skips_slash_skills_in_protected_regions() -> None:
    text = (
        "```text\n/sase_plan\n```\n"
        "%xprompts_enabled:false\n/sase_plan\n"
        "%xprompts_enabled:true\n/sase_plan"
    )

    assert _source_by_kind(
        text,
        "skill",
        known_skills=frozenset({"sase_plan"}),
    ) == ["/sase_plan"]


def test_tokenize_empty_known_skills_preserves_preview_behavior() -> None:
    text = "/sase_plan then #gh:sase"

    assert _source_by_kind(text, "skill") == []
    assert _source_by_kind(text, "invocation") == ["#gh"]


def test_tokenize_slash_skill_coexists_in_sorted_source_order() -> None:
    text = "/sase_plan #gh:sase %auto\n---"
    spans = xprompt_inspect.tokenize(
        text,
        known_skills=frozenset({"sase_plan"}),
    )

    assert [span.kind for span in spans] == [
        "skill",
        "invocation",
        "invocation_arg",
        "directive",
        "separator",
    ]
    assert spans == sorted(spans, key=lambda span: (span.start, span.end))
