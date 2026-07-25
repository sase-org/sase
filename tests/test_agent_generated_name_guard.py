"""Guards that stop the runtime from generating non-terminal role names.

Historical names such as ``4x--epic.f-0`` and ``fi--code.f0--code`` were
written by SASE itself: resume-derived naming and family attachment appended
to a base that already carried a ``--<role>`` suffix. Classification of those
names on disk is total, but generation stays strict.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.agent.clan_membership import (
    ClanMembershipError,
    resolve_or_create_clan_membership,
)
from sase.agent.family_attach import (
    FamilyAttachDirective,
    FamilyAttachError,
    resolve_family_attach_plan,
)
from sase.agent.names import (
    generated_agent_name_is_valid,
    generated_child_name_base,
    resume_agent_name_template,
    retry_agent_name_template,
    wait_agent_name_template,
)
from sase.xprompt._exceptions import DirectiveError
from tests._dynamic_agent_family_attach_helpers import (
    _artifact_record,
    _patch_attach_snapshot,
)
from tests.test_parallel_agent_family_launch import _launch_with_captured_spawns


class TestGeneratedNameValidity:
    @pytest.mark.parametrize(
        "name",
        ["foo", "foo.bar", "foo.bar.baz--code", "foo--0"],
    )
    def test_well_formed_names_stay_valid(self, name: str) -> None:
        assert generated_agent_name_is_valid(name)

    @pytest.mark.parametrize(
        "name",
        ["4x--epic.f-0", "fi--code.f0--plan", "fi--code.f0--code", "fi--code.f0"],
    )
    def test_historical_names_are_invalid_to_generate(self, name: str) -> None:
        assert not generated_agent_name_is_valid(name)


class TestGeneratedChildNameBase:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("foo", "foo"),
            ("foo.bar", "foo.bar"),
            ("research.worker", "research.worker"),
            ("foo--code", "foo"),
            ("foo.bar--plan", "foo.bar"),
            ("fi--code.f0", "fi"),
            ("4x--epic.f-0", "4x"),
        ],
    )
    def test_base_can_always_parent_a_dotted_child(
        self, name: str, expected: str
    ) -> None:
        assert generated_child_name_base(name) == expected
        assert generated_agent_name_is_valid(f"{generated_child_name_base(name)}.f0")


class TestDerivedNameTemplates:
    def test_solo_bases_are_unchanged(self) -> None:
        assert resume_agent_name_template("foo") == "foo.f@"
        assert wait_agent_name_template("foo.bar") == "foo.bar.w@"
        assert retry_agent_name_template("foo") == "foo.r@"

    def test_family_member_bases_hang_off_the_family_name(self) -> None:
        assert resume_agent_name_template("foo--code") == "foo.f@"
        assert wait_agent_name_template("foo--code") == "foo.w@"
        assert retry_agent_name_template("foo--code") == "foo.r@"

    def test_legacy_bases_fall_back_to_their_hood(self) -> None:
        assert resume_agent_name_template("fi--code.f0") == "fi.f@"
        assert wait_agent_name_template("4x--epic.f-0") == "4x.w@"


class TestFamilyAttachGeneratedNames:
    def test_attaching_to_a_family_member_parent_uses_the_family_base(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_attach_snapshot(
            monkeypatch,
            [
                _artifact_record(
                    name="foo--code",
                    agent_family="foo",
                    role_suffix="--code",
                )
            ],
        )

        plan = resolve_family_attach_plan(
            FamilyAttachDirective(parent="foo--code", suffix="reviewer"),
            project_name="sase",
        )

        assert plan.agent_name == "foo--reviewer"
        assert generated_agent_name_is_valid(plan.agent_name)

    def test_attaching_to_a_clan_member_parent_stays_terminal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_attach_snapshot(
            monkeypatch,
            [
                _artifact_record(
                    name="research.worker",
                    agent_clan="research",
                    agent_clan_generation="20260701010000",
                )
            ],
        )

        plan = resolve_family_attach_plan(
            FamilyAttachDirective(parent="research.worker", suffix="reviewer"),
            project_name="sase",
        )

        assert plan.agent_name == "research.worker--reviewer"
        assert plan.parent_family_member_name == "research.worker--0"
        assert generated_agent_name_is_valid(plan.agent_name)

    def test_legacy_parent_fails_with_an_actionable_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_attach_snapshot(
            monkeypatch,
            [_artifact_record(name="fi--code.f0", agent_family="fi--code.f0")],
        )

        with pytest.raises(FamilyAttachError) as exc_info:
            resolve_family_attach_plan(
                FamilyAttachDirective(parent="fi--code.f0", suffix="code"),
                project_name="sase",
            )

        message = str(exc_info.value)
        assert "fi--code.f0" in message
        assert "fi--code.f0--code" in message
        assert "outside the final name segment" in message


class TestClanNameGuard:
    def test_clan_launch_rejects_a_family_marked_clan_before_spawn(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

        with pytest.raises(DirectiveError, match="outside the final name segment"):
            _launch_with_captured_spawns(["%id:fi--code.one\n%clan:fi--code\nWork"])

    def test_clan_carrying_a_family_marker_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ClanMembershipError) as exc_info:
            resolve_or_create_clan_membership(
                "fi--code",
                generation="20260701010101",
                claiming_dir=str(tmp_path),
            )

        message = str(exc_info.value)
        assert "fi--code" in message
        assert "outside the final name segment" in message
