"""Commit footer formatting, parsing, and owned tag behavior."""

from __future__ import annotations

from sase.workflows.commit.runtime_tags import (
    LinkedCommitTagValue,
    RUNTIME_COMMIT_TAG_KEYS,
    apply_auto_commit_tags_with_runtime,
    apply_auto_commit_type_tag,
    apply_runtime_commit_tags,
    apply_tracked_commit_tags,
    filter_runtime_owned_tags,
    parse_trailing_commit_tags,
    update_trailing_commit_tags,
)
from _commit_runtime_tags_test_support import clean_runtime_env as clean_runtime_env


def test_update_trailing_tags_adds_runtime_tags() -> None:
    assert (
        update_trailing_commit_tags(
            "Fix bug",
            {"AGENT": "agent-a", "MACHINE": "machine-a"},
            remove_keys=RUNTIME_COMMIT_TAG_KEYS,
        )
        == "Fix bug\n\nSASE_AGENT=agent-a\nSASE_MACHINE=machine-a"
    )


def test_update_trailing_tags_preserves_existing_metadata() -> None:
    assert update_trailing_commit_tags(
        "Fix bug\n\nPLAN=sdd/plans/plan.md\nBUG=123",
        {"AGENT": "agent-a", "MACHINE": "machine-a"},
        remove_keys=RUNTIME_COMMIT_TAG_KEYS,
    ) == (
        "Fix bug\n\nSASE_PLAN=sdd/plans/plan.md\nSASE_BUG=123"
        "\nSASE_AGENT=agent-a\nSASE_MACHINE=machine-a"
    )


def test_update_trailing_tags_replaces_stale_runtime_tags() -> None:
    message = "Fix bug\n\nBUG=123\nAGENT=old-agent\nMACHINE=old-machine"

    updated = update_trailing_commit_tags(
        message,
        {"AGENT": "agent-a", "MACHINE": "machine-a"},
        remove_keys=RUNTIME_COMMIT_TAG_KEYS,
    )

    assert (
        updated == "Fix bug\n\nSASE_BUG=123\nSASE_AGENT=agent-a\nSASE_MACHINE=machine-a"
    )
    assert "old-agent" not in updated
    assert "old-machine" not in updated
    assert updated.count("AGENT=") == 1
    assert updated.count("MACHINE=") == 1


def test_update_trailing_tags_render_every_owned_builtin_prefixed() -> None:
    """TYPE, AGENT, MACHINE, PLAN, and BUG all render with the SASE_ prefix."""
    updated = update_trailing_commit_tags(
        "Fix bug",
        {
            "TYPE": "sdd",
            "AGENT": "agent-a",
            "MACHINE": "machine-a",
            "PLAN": "sdd/plans/plan.md",
            "BUG": "123",
        },
    )

    assert updated == (
        "Fix bug\n\nSASE_TYPE=sdd\nSASE_AGENT=agent-a\nSASE_MACHINE=machine-a"
        "\nSASE_PLAN=sdd/plans/plan.md\nSASE_BUG=123"
    )


def test_update_trailing_tags_prefixed_input_key_is_not_double_prefixed() -> None:
    """An already-prefixed input key renders once, replacing the legacy alias."""
    updated = update_trailing_commit_tags(
        "Fix bug\n\nTYPE=old",
        {"SASE_TYPE": "new"},
        remove_keys={"SASE_TYPE"},
    )

    assert updated == "Fix bug\n\nSASE_TYPE=new"
    assert "SASE_SASE_TYPE" not in updated
    assert "TYPE=old" not in updated


def test_update_trailing_tags_removes_legacy_and_prefixed_aliases() -> None:
    """Updating an owned key drops both spellings already present in the block."""
    updated = update_trailing_commit_tags(
        "Fix bug\n\nTYPE=legacy\nSASE_TYPE=stale\nTEAM=infra",
        {"TYPE": "fresh"},
        remove_keys={"TYPE"},
    )

    assert updated == "Fix bug\n\nSASE_TEAM=infra\nSASE_TYPE=fresh"
    assert updated.count("TYPE=") == 1
    assert "TYPE=legacy" not in updated
    assert "SASE_TYPE=stale" not in updated


def test_auto_commit_type_tag_adds_type() -> None:
    assert apply_auto_commit_type_tag("Fix bug", "sdd") == "Fix bug\n\nSASE_TYPE=sdd"


def test_auto_commit_type_tag_replaces_stale_type_and_preserves_other_tags() -> None:
    updated = apply_auto_commit_type_tag(
        "Fix bug\n\nBUG=123\nTYPE=old\nTEAM=infra",
        "bead_work",
    )

    assert updated == "Fix bug\n\nSASE_BUG=123\nSASE_TEAM=infra\nSASE_TYPE=bead_work"
    assert "TYPE=old" not in updated


def test_auto_commit_type_tag_composes_with_runtime_tags_without_owning_type() -> None:
    message = apply_auto_commit_type_tag("Fix bug", "sdd")

    updated = update_trailing_commit_tags(
        message,
        {"AGENT": "agent-a", "MACHINE": "machine-a"},
        remove_keys=RUNTIME_COMMIT_TAG_KEYS,
    )

    assert "TYPE" not in RUNTIME_COMMIT_TAG_KEYS
    assert updated == (
        "Fix bug\n\nSASE_TYPE=sdd\nSASE_AGENT=agent-a\nSASE_MACHINE=machine-a"
    )


def test_parse_trailing_commit_tags_reads_legacy_block() -> None:
    assert parse_trailing_commit_tags("Subject\n\nAGENT=foo\nTYPE=sdd") == {
        "AGENT": "foo",
        "TYPE": "sdd",
    }
    assert parse_trailing_commit_tags("Subject only") == {}


def test_parse_trailing_commit_tags_canonicalizes_prefixed_block() -> None:
    """New ``SASE_``-prefixed footer lines parse to canonical keys."""
    assert parse_trailing_commit_tags("Subject\n\nSASE_AGENT=foo\nSASE_TYPE=sdd") == {
        "AGENT": "foo",
        "TYPE": "sdd",
    }


def test_parse_trailing_commit_tags_prefixed_wins_over_legacy() -> None:
    """When both spellings are present, the later (prefixed) line wins."""
    assert parse_trailing_commit_tags("Subject\n\nAGENT=old\nSASE_AGENT=new") == {
        "AGENT": "new",
    }


def test_update_trailing_tags_keeps_body_text_intact() -> None:
    assert (
        update_trailing_commit_tags(
            "Fix bug\n\nBody line",
            {"MACHINE": "machine-a"},
            remove_keys=RUNTIME_COMMIT_TAG_KEYS,
        )
        == "Fix bug\n\nBody line\n\nSASE_MACHINE=machine-a"
    )


def test_runtime_update_preserves_linked_plan_footer() -> None:
    message = (
        "Fix bug\n\nSASE_PLAN=[202607/plan.md][1]\n\n"
        "[1]: https://github.com/acme/plans/blob/main/202607/plan.md"
    )

    updated = update_trailing_commit_tags(
        message,
        {"AGENT": "agent-a", "MACHINE": "athena"},
        remove_keys=RUNTIME_COMMIT_TAG_KEYS,
    )

    assert updated == (
        "Fix bug\n\nSASE_PLAN=[202607/plan.md][1]\n"
        "SASE_AGENT=agent-a\nSASE_MACHINE=athena\n\n"
        "[1]: https://github.com/acme/plans/blob/main/202607/plan.md"
    )
    assert parse_trailing_commit_tags(updated)["PLAN"] == "202607/plan.md"


def test_linked_agent_follows_existing_plan_reference_number() -> None:
    message = (
        "Fix bug\n\nSASE_PLAN=[202607/plan.md][1]\n\n"
        "[1]: https://github.com/acme/plans/blob/main/202607/plan.md"
    )

    updated = update_trailing_commit_tags(
        message,
        {
            "AGENT": LinkedCommitTagValue(
                "alice.athena.foo--code",
                "https://github.com/acme/project--agents/blob/main/"
                "families/alice.athena.foo.md#member-code",
            )
        },
        remove_keys=RUNTIME_COMMIT_TAG_KEYS,
    )

    assert "SASE_PLAN=[202607/plan.md][1]" in updated
    assert "SASE_AGENT=[alice.athena.foo--code][2]" in updated
    assert (
        "[2]: https://github.com/acme/project--agents/blob/main/"
        "families/alice.athena.foo.md#member-code"
    ) in updated


def test_linked_update_is_idempotent_and_removes_replaced_definition() -> None:
    first = update_trailing_commit_tags(
        "Fix bug",
        {
            "PLAN": LinkedCommitTagValue(
                "old.md",
                "https://github.com/acme/plans/blob/main/old.md",
            )
        },
        remove_keys={"PLAN"},
    )
    second = update_trailing_commit_tags(
        first,
        {
            "PLAN": LinkedCommitTagValue(
                "new.md",
                "https://github.com/acme/plans/blob/main/new.md",
            )
        },
        remove_keys={"PLAN"},
    )
    repeated = update_trailing_commit_tags(
        second,
        {
            "PLAN": LinkedCommitTagValue(
                "new.md",
                "https://github.com/acme/plans/blob/main/new.md",
            )
        },
        remove_keys={"PLAN"},
    )

    assert second == repeated
    assert "old.md" not in second
    assert "SASE_PLAN=[new.md][2]" in second
    assert "[2]: https://github.com/acme/plans/blob/main/new.md" in second


def test_body_markdown_definition_is_not_mistaken_for_footer_metadata() -> None:
    message = (
        "Fix bug\n\nSASE_PLAN=body-like-text\n\n"
        "[1]: https://example.test/body\n\nTrailing prose"
    )

    updated = update_trailing_commit_tags(message, {"TYPE": "sdd"})

    assert updated.startswith(message)
    assert updated.endswith("SASE_TYPE=sdd")


def test_filter_runtime_owned_tags() -> None:
    assert filter_runtime_owned_tags(
        {
            "TEAM": "infra",
            "BEAD": "sase-ai.2",
            "AGENT": "old",
            "MODEL": "old/model",
            "MACHINE": "old",
        }
    ) == {"TEAM": "infra", "BEAD": "sase-ai.2"}


def test_filter_runtime_owned_tags_handles_prefixed_keys() -> None:
    """Runtime-owned keys are filtered in either spelling."""
    assert filter_runtime_owned_tags(
        {
            "SASE_TEAM": "infra",
            "SASE_AGENT": "old",
            "SASE_MODEL": "old/model",
            "SASE_MACHINE": "old",
        }
    ) == {"SASE_TEAM": "infra"}
