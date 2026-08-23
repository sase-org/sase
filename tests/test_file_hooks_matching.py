"""Tests for file-hook event matching.

Config-loading coverage lives in ``test_file_hooks_loader.py``.
"""

from __future__ import annotations

import pytest

from sase.config.file_hooks import (
    FileHookConfig,
    FileHookFilters,
    hook_matches_event,
    match_events,
)
from tests._file_hooks_helpers import _event, _hook


def test_path_glob_positive_or_and_negative_veto() -> None:
    hook = _hook(path_globs=("src/*.py", "tests/*.py", "!tests/private*.py"))

    assert hook_matches_event(hook, _event("src/main.py"))
    assert hook_matches_event(hook, _event("tests/test_main.py"))
    assert not hook_matches_event(hook, _event("tests/private_test.py"))
    assert not hook_matches_event(hook, _event("docs/main.py"))


def test_negative_only_path_globs_mean_everything_except() -> None:
    hook = _hook(path_globs=("!**/*__*.md",))

    assert hook_matches_event(hook, _event("202607/report/report.md"))
    assert not hook_matches_event(hook, _event("202607/report/report__draft.md"))


def test_star_does_not_cross_slashes_and_globstar_does() -> None:
    shallow = _hook(path_globs=("src/*.py",))
    recursive = _hook(path_globs=("src/**/*.py",))

    assert hook_matches_event(shallow, _event("src/main.py"))
    assert not hook_matches_event(shallow, _event("src/nested/main.py"))
    assert hook_matches_event(recursive, _event("src/nested/main.py"))


def test_dotglob_and_posix_path_normalization() -> None:
    hook = _hook(path_globs=("src/**/*.py",))

    assert hook_matches_event(hook, _event(r".\src\.hidden\check.py"))


def test_positive_agent_name_globs_match_only_listed_agents() -> None:
    hook = _hook(agent_name_globs=("research.*.final", "bob"))

    assert hook_matches_event(hook, _event("report.md", agent="research.7.final"))
    assert hook_matches_event(hook, _event("report.md", agent="bob"))
    assert not hook_matches_event(hook, _event("report.md", agent="research.7.cld"))


def test_negative_only_agent_name_globs_mean_everything_except() -> None:
    hook = _hook(agent_name_globs=("!research.*.cld", "!research.*.cdx"))

    assert not hook_matches_event(hook, _event("report.md", agent="research.7.cld"))
    assert not hook_matches_event(hook, _event("report.md", agent="research.7.cdx"))
    assert hook_matches_event(hook, _event("report.md", agent="research.7.final"))
    assert hook_matches_event(hook, _event("report.md", agent="bbugyi200.athena.cld"))


def test_mixed_agent_name_globs_or_positives_then_apply_the_veto() -> None:
    hook = _hook(agent_name_globs=("research.*", "!research.*.cld"))

    assert hook_matches_event(hook, _event("report.md", agent="research.7.final"))
    assert not hook_matches_event(hook, _event("report.md", agent="research.7.cld"))
    assert not hook_matches_event(hook, _event("report.md", agent="bob"))


def test_unattributed_event_clears_only_negative_only_agent_globs() -> None:
    negative_only = _hook(agent_name_globs=("!research.*.cld",))
    with_positive = _hook(agent_name_globs=("research.*", "!research.*.cld"))

    assert hook_matches_event(negative_only, _event("report.md"))
    assert not hook_matches_event(with_positive, _event("report.md"))


def test_path_and_agent_name_filters_are_anded() -> None:
    hook = _hook(
        path_globs=("20*/**/*.md", "!20*/*/*__*.md"),
        agent_name_globs=("!research.*.cld", "!research.*.cdx"),
    )

    assert hook_matches_event(hook, _event("202608/foo.md", agent="research.7.final"))
    assert hook_matches_event(
        hook,
        _event("202608/foo/foo.md", agent="research.7.final"),
    )
    assert not hook_matches_event(hook, _event("202608/foo.md", agent="research.7.cld"))
    assert not hook_matches_event(
        hook,
        _event("202608/foo/foo__a.md", agent="research.7.final"),
    )


def test_project_sidecar_and_op_filters_and_unrestricted_defaults() -> None:
    restricted = _hook(
        projects=("sase",),
        sidecars=("research",),
        ops=("ADD",),
    )
    unrestricted = _hook()

    assert hook_matches_event(restricted, _event("report.md"))
    assert not hook_matches_event(restricted, _event("report.md", project="other"))
    assert not hook_matches_event(restricted, _event("report.md", sidecar="plans"))
    assert not hook_matches_event(restricted, _event("report.md", op="MODIFY"))
    assert hook_matches_event(
        unrestricted,
        _event("anything.txt", project="other", sidecar=None, op="REMOVE"),
    )


def test_non_user_causes_are_opt_in_while_user_still_matches() -> None:
    unrestricted = _hook()
    referenced_by = _hook(causes=("referenced_by",))

    assert hook_matches_event(unrestricted, _event("report.md", cause="user"))
    assert not hook_matches_event(
        unrestricted,
        _event("report.md", cause="referenced_by"),
    )
    assert hook_matches_event(
        referenced_by,
        _event("report.md", cause="referenced_by"),
    )
    assert hook_matches_event(referenced_by, _event("report.md", cause="user"))


@pytest.mark.parametrize(
    "producer",
    ["artifact", "commit", "sdd", "finalizer", "dispatch"],
)
def test_omitted_producers_filter_matches_every_producer(producer: str) -> None:
    hook = _hook()

    assert hook_matches_event(hook, _event("report.md"), producer=producer)


def test_explicit_producers_filter_is_anded_with_other_dimensions() -> None:
    hook = _hook(producers=("commit", "sdd", "finalizer"), ops=("ADD",))
    event = _event("report.md")

    assert hook_matches_event(hook, event, producer="commit")
    assert hook_matches_event(hook, event, producer="sdd")
    assert hook_matches_event(hook, event, producer="finalizer")
    assert not hook_matches_event(hook, event, producer="artifact")
    assert not hook_matches_event(hook, event, producer="dispatch")
    assert not hook_matches_event(hook, event)
    assert not hook_matches_event(
        hook,
        _event("report.md", op="MODIFY"),
        producer="commit",
    )


def test_match_events_applies_producer_filter() -> None:
    restricted = _hook(producers=("commit", "finalizer"))
    unrestricted = FileHookConfig(
        name="unrestricted",
        description=None,
        command="check-two",
        timeout_seconds=120,
        filters=FileHookFilters(),
    )
    events = [_event("one.md")]

    assert [
        (run.hook.name, run.event.rel_path)
        for run in match_events(
            [restricted, unrestricted],
            events,
            producer="artifact",
        )
    ] == [("unrestricted", "one.md")]
    assert [
        (run.hook.name, run.event.rel_path)
        for run in match_events(
            [restricted, unrestricted],
            events,
            producer="commit",
        )
    ] == [("test-hook", "one.md"), ("unrestricted", "one.md")]


def test_match_events_returns_hook_order_then_event_order() -> None:
    first = _hook(path_globs=("**/*.md",))
    second = FileHookConfig(
        name="second",
        description=None,
        command="check-two",
        timeout_seconds=120,
        filters=FileHookFilters(),
    )
    events = [_event("one.md"), _event("two.txt")]

    runs = match_events([first, second], events)

    assert [(run.hook.name, run.event.rel_path) for run in runs] == [
        ("test-hook", "one.md"),
        ("second", "one.md"),
        ("second", "two.txt"),
    ]
