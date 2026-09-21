"""CLI coverage for ``sase bead touched``."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from sase.bead import cli_touched
from sase.bead.cli_touched import (
    _filter_touches_by_verbs,
    _format_verb_chips,
    handle_bead_touched,
    _order_touches_newest_first,
    _touch_glyph,
)
from sase.core.agent_identity_facade import AgentIdentitySnapshot
from sase.core.bead_touch_index_facade import (
    BeadTouch,
    BeadTouchQuery,
    FoldedBeadTouch,
    fold_touches_per_bead,
)
from tests.main.parser_cli_helpers import parse_sase_args
from tests.main.parser_help_helpers import help_subcommand_rows, parser_for

_OWNERLESS = AgentIdentitySnapshot(None, (), ())


def _touch(
    bead_id: str,
    verbs: dict[str, int],
    last_at: str = "",
    *,
    actor: str = "0oa",
    title: str = "",
    issue_type: str = "task",
    status: str = "open",
    first_at: str | None = None,
) -> BeadTouch:
    return BeadTouch(
        actor=actor,
        bead_id=bead_id,
        title=title or f"Title {bead_id}",
        issue_type=issue_type,
        status=status,
        verbs=dict(verbs),
        first_at=last_at if first_at is None else first_at,
        last_at=last_at,
    )


def _folded(
    bead_id: str,
    verbs: dict[str, int],
    last_at: str = "",
    *,
    title: str = "",
    actors: tuple[str, ...] = ("0oa",),
) -> FoldedBeadTouch:
    return FoldedBeadTouch(
        bead_id=bead_id,
        title=title or f"Title {bead_id}",
        issue_type="task",
        status="open",
        verbs=dict(verbs),
        first_at=last_at,
        last_at=last_at,
        actors=actors,
    )


def _stub_touched(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    touches: list[BeadTouch],
    *,
    views: list[BeadTouch] | None = None,
    reads: list[BeadTouch] | None = None,
) -> None:
    import sase.core.agent_identity_facade as identity_facade
    import sase.core.bead_touch_index_facade as touch_facade

    monkeypatch.setattr(
        AgentIdentitySnapshot, "current", classmethod(lambda cls: _OWNERLESS)
    )
    monkeypatch.setattr(
        identity_facade,
        "globalize_owned_agent_name",
        lambda name, identity=None: name,
    )
    monkeypatch.setattr(
        touch_facade, "touch_index_path", lambda *args, **kwargs: tmp_path / "t.json"
    )
    monkeypatch.setattr(
        touch_facade,
        "query_touches_for_agent",
        lambda index_path, **kwargs: BeadTouchQuery(
            schema_version=1, generation="2026-09-20T00:00:00Z", touches=tuple(touches)
        ),
    )
    monkeypatch.setattr(
        touch_facade,
        "resolve_touch_index_project",
        lambda *args, **kwargs: "test-proj",
    )
    monkeypatch.setattr(
        cli_touched,
        "_load_view_touches",
        lambda **kwargs: list(views or []),
    )
    monkeypatch.setattr(
        cli_touched,
        "_load_read_touches",
        lambda **kwargs: list(reads or []),
    )


def _args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "agent": "0oa",
        "json": False,
        "limit": None,
        "verb": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test__touch_glyph_precedence_and_single_cell() -> None:
    assert _touch_glyph({"created": 1, "closed": 1}) == "✚"
    assert _touch_glyph({"closed": 1, "reopened": 1}) == "✓"
    assert _touch_glyph({"reopened": 1, "noted": 2}) == "↻"
    assert _touch_glyph({"noted": 2}) == "✎"
    assert _touch_glyph({"+1": 3}) == "✎"
    assert _touch_glyph({"read": 1, "viewed": 1}) == "←"
    assert _touch_glyph({"viewed": 1, "removed": 1}) == "◇"
    assert _touch_glyph({"removed": 1}) == "⌫"
    assert _touch_glyph({}) == "◇"
    for verbs in (
        {"created": 1},
        {"updated": 1},
        {"noted": 1},
        {"closed": 1},
        {"reopened": 1},
        {"+1": 1},
        {"ready": 1},
        {"snoozed": 1},
        {"dep": 1},
        {"linked": 1},
        {"ref": 1},
        {"removed": 1},
        {"read": 1},
        {"viewed": 1},
    ):
        assert len(_touch_glyph(verbs)) == 1


def test__format_verb_chips_fixed_order_and_counts() -> None:
    assert _format_verb_chips({"noted": 2, "created": 1}) == "created · noted ×2"
    assert _format_verb_chips({"noted": 1, "read": 2, "viewed": 1}) == (
        "noted · read ×2 · viewed"
    )
    assert _format_verb_chips({}) == ""


def test__order_folded_newest_first_undated_last() -> None:
    rows = _order_touches_newest_first(
        [
            _folded("sase-3", {"noted": 1}),
            _folded("sase-1", {"noted": 1}, "2026-09-19T00:00:00Z"),
            _folded("sase-2", {"noted": 1}, "2026-09-20T00:00:00Z"),
        ]
    )
    assert [touch.bead_id for touch in rows] == ["sase-2", "sase-1", "sase-3"]


def test__filter_touches_by_verbs() -> None:
    rows = _filter_touches_by_verbs(
        [_folded("sase-1", {"created": 1}), _folded("sase-2", {"noted": 1})],
        ["noted", "closed"],
    )
    assert [touch.bead_id for touch in rows] == ["sase-2"]


def test_fold_merges_mixed_actor_spellings_per_bead() -> None:
    folded = fold_touches_per_bead(
        [
            _touch(
                "sase-1",
                {"created": 1},
                "2026-09-19T00:00:00Z",
                actor="bbugyi200.athena.0oa",
                first_at="2026-09-18T00:00:00Z",
            ),
            _touch(
                "sase-1",
                {"noted": 2},
                "2026-09-20T00:00:00Z",
                actor="0oa",
                title="",
                first_at="2026-09-19T12:00:00Z",
            ),
        ]
    )
    assert len(folded) == 1
    row = folded[0]
    assert row.bead_id == "sase-1"
    assert row.verbs == {"created": 1, "noted": 2}
    assert row.first_at == "2026-09-18T00:00:00Z"
    assert row.last_at == "2026-09-20T00:00:00Z"
    assert row.title == "Title sase-1"
    assert row.actors == ("0oa", "bbugyi200.athena.0oa")


def test_fold_keeps_durable_title_over_views_and_reads() -> None:
    folded = fold_touches_per_bead(
        [
            _touch("sase-1", {"noted": 1}, "2026-09-20T15:00:00Z"),
            BeadTouch(actor="0oa", bead_id="sase-1", verbs={"viewed": 1}),
            BeadTouch(actor="0oa", bead_id="sase-1", verbs={"read": 1}),
        ]
    )
    assert folded[0].title == "Title sase-1"
    assert folded[0].verbs == {"noted": 1, "viewed": 1, "read": 1}


def test_parser_registers_touched_with_short_aliases() -> None:
    args = parse_sase_args(
        ["bead", "touched", "0oa", "-v", "noted", "-v", "closed", "-l", "5", "-j"]
    )
    assert args.bead_subcommand == "touched"
    assert args.agent == "0oa"
    assert args.verb == ["noted", "closed"]
    assert args.limit == 5
    assert args.json is True
    assert not hasattr(args, "all")

    bead_help = parser_for(("sase", "bead")).format_help()
    rows = help_subcommand_rows(
        bead_help,
        {
            "task-type",
            "touched",
            "update",
        },
    )
    assert rows.index("task-type") < rows.index("touched") < rows.index("update")

    touched_help = parser_for(("sase", "bead", "touched")).format_help()
    for token in ("-j", "--json", "-l", "--limit", "-v", "--verb"):
        assert token in touched_help
    assert "--all" not in touched_help
    assert "machine-local" in touched_help
    assert "sase-159" in touched_help
    assert "touched beads only" in touched_help


def test_parser_rejects_removed_all_flag() -> None:
    with pytest.raises(SystemExit):
        parse_sase_args(["bead", "touched", "0oa", "-a"])


def test_handle_compact_lists_newest_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub_touched(
        monkeypatch,
        tmp_path,
        [
            _touch("sase-1", {"created": 1}, "2026-09-19T00:00:00Z"),
            _touch("sase-2", {"noted": 2}, "2026-09-20T00:00:00Z"),
        ],
    )
    handle_bead_touched(_args())
    out = capsys.readouterr().out
    assert out.index("sase-2") < out.index("sase-1")
    assert "noted ×2" in out
    assert "Title sase-2" in out


def test_handle_folds_duplicate_bead_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub_touched(
        monkeypatch,
        tmp_path,
        [
            _touch(
                "sase-1",
                {"created": 1},
                "2026-09-19T00:00:00Z",
                actor="bbugyi200.athena.0oa",
            ),
            _touch("sase-1", {"noted": 2}, "2026-09-20T00:00:00Z", actor="0oa"),
        ],
    )
    handle_bead_touched(_args())
    out = capsys.readouterr().out
    assert out.count("✚ sase-1") == 1
    assert len([line for line in out.splitlines() if "sase-1" in line]) == 1
    assert "noted ×2" in out


def test_handle_merges_views_behind_durable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub_touched(
        monkeypatch,
        tmp_path,
        [_touch("sase-1", {"noted": 1}, "2026-09-19T00:00:00Z")],
        views=[
            BeadTouch(
                actor="0oa",
                bead_id="sase-1",
                verbs={"viewed": 2},
                first_at="2026-09-20T15:00:00Z",
                last_at="2026-09-20T16:00:00Z",
            ),
            BeadTouch(
                actor="0oa",
                bead_id="sase-9v",
                verbs={"viewed": 1},
                first_at="2026-09-20T17:00:00Z",
                last_at="2026-09-20T17:00:00Z",
            ),
        ],
    )
    handle_bead_touched(_args())
    out = capsys.readouterr().out
    assert "Title sase-1" in out
    assert "viewed ×2" in out
    assert "sase-9v" in out

    handle_bead_touched(_args(verb=["viewed"]))
    out = capsys.readouterr().out
    assert "sase-1" in out
    assert "sase-9v" in out


def test_handle_counts_audited_reads_as_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub_touched(
        monkeypatch,
        tmp_path,
        [_touch("sase-1", {"noted": 1}, "2026-09-19T00:00:00Z")],
        reads=[
            BeadTouch(
                actor="0oa",
                bead_id="sase-1",
                verbs={"read": 2},
                first_at="2026-09-20T10:00:00Z",
                last_at="2026-09-20T10:00:00Z",
            ),
        ],
    )
    handle_bead_touched(_args(verb=["read"]))
    out = capsys.readouterr().out
    assert "sase-1" in out
    assert "read ×2" in out
    assert "viewed" not in out


def test_handle_json_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub_touched(
        monkeypatch, tmp_path, [_touch("sase-1", {"closed": 1}, "2026-09-19T00:00:00Z")]
    )
    handle_bead_touched(_args(json=True))
    payload = json.loads(capsys.readouterr().out)
    assert payload["agent"] == "0oa"
    assert payload["total"] == 1
    row = payload["touches"][0]
    assert row["bead_id"] == "sase-1"
    assert row["verbs"] == {"closed": 1}
    assert row["title"] == "Title sase-1"
    assert row["issue_type"] == "task"
    assert row["status"] == "open"
    assert row["first_at"] == "2026-09-19T00:00:00Z"
    assert row["last_at"] == "2026-09-19T00:00:00Z"
    assert row["actors"] == ["0oa"]
    assert "actor" not in row


def test_handle_empty_reports_no_touches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub_touched(monkeypatch, tmp_path, [])
    handle_bead_touched(_args())
    assert capsys.readouterr().out.strip() == "No beads touched by 0oa."


def test_handle_unknown_verb_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub_touched(monkeypatch, tmp_path, [])
    with pytest.raises(SystemExit) as excinfo:
        handle_bead_touched(_args(verb=["frobnicate"]))
    assert excinfo.value.code == 2
    assert "unknown verb" in capsys.readouterr().err


def test_handle_limit_truncates_with_more_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub_touched(
        monkeypatch,
        tmp_path,
        [
            _touch("sase-1", {"noted": 1}, "2026-09-19T00:00:00Z"),
            _touch("sase-2", {"noted": 1}, "2026-09-20T00:00:00Z"),
        ],
    )
    handle_bead_touched(_args(limit=1))
    out = capsys.readouterr().out
    assert "sase-2" in out
    assert "sase-1" not in out
    assert "+1 more" in out


def test_cli_touched_exports_cover_handler_helpers() -> None:
    assert "handle_bead_touched" in cli_touched.__all__
