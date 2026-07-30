"""Command palette applicability predicates for the ChangeSpecs tab."""

from __future__ import annotations

from sase.ace.changespec import CommitEntry
from sase.ace.tui.commands import CommandContext, is_command_available
from tests._command_availability_helpers import (
    catalog_by_id as _catalog_by_id,
    make_changespec as _make_changespec,
)


def test_bug_commands_only_available_on_bugs_subtab() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.create_bug"]
    assert is_command_available(
        spec,
        CommandContext(tab="changespecs", artifacts_subtab="bugs"),
    )
    assert not is_command_available(
        spec,
        CommandContext(tab="changespecs", artifacts_subtab="prs"),
    )
    assert not is_command_available(
        spec,
        CommandContext(tab="changespecs", artifacts_subtab="plans"),
    )


def test_app_edit_query_is_available_on_prs_commits_plans_and_axe() -> None:
    spec = _catalog_by_id()["app.edit_query"]
    assert is_command_available(
        spec,
        CommandContext(tab="changespecs", artifacts_subtab="prs"),
    )
    assert is_command_available(
        spec,
        CommandContext(tab="changespecs", artifacts_subtab="commits"),
    )
    assert is_command_available(
        spec,
        CommandContext(tab="changespecs", artifacts_subtab="plans"),
    )
    assert not is_command_available(
        spec,
        CommandContext(tab="changespecs", artifacts_subtab="bugs"),
    )
    assert is_command_available(spec, CommandContext(tab="axe"))
    assert not is_command_available(spec, CommandContext(tab="agents"))


def test_leader_edit_query_is_agents_only() -> None:
    spec = _catalog_by_id()["leader.edit_query"]

    assert is_command_available(spec, CommandContext(tab="agents"))
    assert not is_command_available(
        spec,
        CommandContext(tab="changespecs", artifacts_subtab="prs"),
    )
    assert not is_command_available(spec, CommandContext(tab="axe"))


def test_plans_filter_command_is_available_only_on_plans() -> None:
    spec = _catalog_by_id()["app.plans_filters"]
    assert is_command_available(
        spec,
        CommandContext(tab="changespecs", artifacts_subtab="plans"),
    )
    for subtab in ("prs", "commits", "bugs"):
        assert not is_command_available(
            spec,
            CommandContext(tab="changespecs", artifacts_subtab=subtab),
        )


def test_artifacts_copy_commands_follow_the_active_subtab() -> None:
    catalog = _catalog_by_id()
    groups = ("commits", "plans", "chats", "bugs", "files")

    for active in groups:
        ctx = CommandContext(tab="changespecs", artifacts_subtab=active)
        for group in groups:
            spec = catalog[f"copy.artifacts_{group}.snapshot"]
            assert is_command_available(spec, ctx) is (group == active)

    prs = CommandContext(tab="changespecs", artifacts_subtab="prs")
    assert all(
        not is_command_available(catalog[f"copy.artifacts_{group}.snapshot"], prs)
        for group in groups
    )


def test_saved_query_picker_and_slots_are_pr_only() -> None:
    catalog = _catalog_by_id()
    picker = catalog["app.open_saved_query_picker"]
    slot = catalog["saved_query.3"]

    for spec in (picker, slot):
        assert is_command_available(
            spec,
            CommandContext(tab="changespecs", artifacts_subtab="prs"),
        )
        assert not is_command_available(
            spec,
            CommandContext(tab="changespecs", artifacts_subtab="commits"),
        )
        assert not is_command_available(spec, CommandContext(tab="agents"))
        assert not is_command_available(spec, CommandContext(tab="axe"))


def test_show_diff_hidden_when_no_cl_selected() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.show_diff"]
    ctx = CommandContext(tab="changespecs", changespec=None)
    assert not is_command_available(spec, ctx)


def test_show_diff_hidden_when_changespec_has_no_pr_number() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.show_diff"]
    cs = _make_changespec(cl=None)
    ctx = CommandContext(tab="changespecs", changespec=cs)
    assert not is_command_available(spec, ctx)


def test_show_diff_visible_with_pr_number() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.show_diff"]
    cs = _make_changespec(cl="12345")
    ctx = CommandContext(tab="changespecs", changespec=cs)
    assert is_command_available(spec, ctx)


def test_agent_run_log_leader_command_requires_selected_cl() -> None:
    catalog = _catalog_by_id()
    spec = catalog["leader.agent_run_log"]
    cs = _make_changespec()

    assert is_command_available(spec, CommandContext(tab="changespecs", changespec=cs))
    assert not is_command_available(
        spec,
        CommandContext(tab="changespecs", changespec=None),
    )
    assert not is_command_available(spec, CommandContext(tab="agents"))


def test_mail_visible_only_for_ready_status() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.mail"]
    ready = _make_changespec(status="Ready")
    draft = _make_changespec(status="Draft")
    assert is_command_available(
        spec, CommandContext(tab="changespecs", changespec=ready)
    )
    assert not is_command_available(
        spec, CommandContext(tab="changespecs", changespec=draft)
    )


def test_reword_hidden_for_submitted_cl() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.reword"]
    cs = _make_changespec(status="Submitted")
    ctx = CommandContext(tab="changespecs", changespec=cs)
    assert not is_command_available(spec, ctx)


def test_rename_cl_hidden_for_reverted_cl() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.rename_cl"]
    cs = _make_changespec(status="Reverted")
    ctx = CommandContext(tab="changespecs", changespec=cs)
    assert not is_command_available(spec, ctx)


def test_accept_proposal_requires_proposed_entry() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.accept_proposal"]
    plain = CommitEntry(number=1, note="plain")
    proposed = CommitEntry(number=2, note="proposed", proposal_letter="a")
    cs_no = _make_changespec(commits=[plain])
    cs_yes = _make_changespec(commits=[plain, proposed])
    assert not is_command_available(
        spec, CommandContext(tab="changespecs", changespec=cs_no)
    )
    assert is_command_available(
        spec, CommandContext(tab="changespecs", changespec=cs_yes)
    )


def test_clear_marks_only_when_marks_exist() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.clear_marks"]
    cs = _make_changespec()
    assert not is_command_available(
        spec, CommandContext(tab="changespecs", changespec=cs, mark_count=0)
    )
    assert is_command_available(
        spec, CommandContext(tab="changespecs", changespec=cs, mark_count=3)
    )


def test_copy_changespecs_pr_number_requires_pr() -> None:
    catalog = _catalog_by_id()
    spec = catalog["copy.changespecs.pr_number"]
    cs_with_cl = _make_changespec(cl="12345")
    cs_without_cl = _make_changespec(cl=None)
    assert is_command_available(
        spec, CommandContext(tab="changespecs", changespec=cs_with_cl)
    )
    assert not is_command_available(
        spec, CommandContext(tab="changespecs", changespec=cs_without_cl)
    )
