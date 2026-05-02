"""Tests for the ``sase sdd`` parser, handler, and link repair commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from sase.main.parser import create_parser
from sase.main.sdd_handler import handle_sdd_command


def _args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "sdd_subcommand": "validate",
        "path": None,
        "json": False,
        "quiet": False,
        "strict": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _write_pair(root: Path, name: str = "linked") -> tuple[Path, Path]:
    prompt = root / "prompts" / "202605" / f"{name}.md"
    plan = root / "tales" / "202605" / f"{name}.md"
    prompt.parent.mkdir(parents=True, exist_ok=True)
    plan.parent.mkdir(parents=True, exist_ok=True)
    prompt.write_text(
        f"---\nplan: sdd/tales/202605/{name}.md\n---\n# Prompt\n",
        encoding="utf-8",
    )
    plan.write_text(
        f"---\nprompt: sdd/prompts/202605/{name}.md\n---\n# Plan\n",
        encoding="utf-8",
    )
    return prompt, plan


def _tier_readmes(root: Path) -> dict[str, Path]:
    return {
        kind: root / kind / "README.md"
        for kind in ("tales", "epics", "legends", "myths")
    }


def test_parser_registers_sdd_subcommands() -> None:
    parser = create_parser()

    args = parser.parse_args(["sdd", "init", "-p", "sdd"])
    assert args.command == "sdd"
    assert args.sdd_subcommand == "init"
    assert args.path == "sdd"

    args = parser.parse_args(["sdd", "validate", "-p", "sdd", "-j", "-q", "--strict"])
    assert args.command == "sdd"
    assert args.sdd_subcommand == "validate"
    assert args.path == "sdd"
    assert args.json is True
    assert args.quiet is True
    assert args.strict is True

    args = parser.parse_args(["sdd", "list", "-p", "sdd", "-k", "prompts", "-j"])
    assert args.sdd_subcommand == "list"
    assert args.kind == "prompts"

    args = parser.parse_args(["sdd", "list", "-p", "sdd", "-k", "tales"])
    assert args.kind == "tales"

    args = parser.parse_args(["sdd", "repair-links", "-p", "sdd", "-w"])
    assert args.write is True


def test_init_creates_readme_for_project_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(_args(sdd_subcommand="init", path=str(tmp_path)))

    assert excinfo.value.code == 0
    readme = tmp_path / "sdd" / "README.md"
    asset = tmp_path / "sdd" / "assets" / "sdd-directory-map.png"
    assert readme.exists()
    assert asset.exists()
    tier_readmes = _tier_readmes(tmp_path / "sdd")
    assert all(path.exists() for path in tier_readmes.values())
    assert str(readme) in capsys.readouterr().out
    text = readme.read_text(encoding="utf-8")
    assert "# Structured Development Docs" in text
    assert "![SDD directory map](assets/sdd-directory-map.png)" in text
    assert "`prompts/`" in text
    assert "`tales/`" in text
    assert "`myths/`" in text
    assert "`sase sdd validate`" in text
    assert "# Tales" in tier_readmes["tales"].read_text(encoding="utf-8")
    assert "task-level implementation plans" in tier_readmes["tales"].read_text(
        encoding="utf-8"
    )
    assert "larger work plans" in tier_readmes["epics"].read_text(encoding="utf-8")
    assert "broad roadmap or strategy" in tier_readmes["legends"].read_text(
        encoding="utf-8"
    )
    assert "long-horizon narrative" in tier_readmes["myths"].read_text(encoding="utf-8")


def test_init_overwrites_stale_readme_and_asset_idempotently(tmp_path: Path) -> None:
    readme = tmp_path / "sdd" / "README.md"
    asset = tmp_path / "sdd" / "assets" / "sdd-directory-map.png"
    readme.parent.mkdir(parents=True)
    readme.write_text("stale\n", encoding="utf-8")
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"stale\n")
    tier_readmes = _tier_readmes(tmp_path / "sdd")
    for tier_readme in tier_readmes.values():
        tier_readme.parent.mkdir(parents=True, exist_ok=True)
        tier_readme.write_text("stale\n", encoding="utf-8")

    with pytest.raises(SystemExit) as first:
        handle_sdd_command(_args(sdd_subcommand="init", path=str(tmp_path)))
    first_content = readme.read_text(encoding="utf-8")
    first_asset_content = asset.read_bytes()
    first_tier_contents = {
        kind: path.read_text(encoding="utf-8") for kind, path in tier_readmes.items()
    }

    with pytest.raises(SystemExit) as second:
        handle_sdd_command(_args(sdd_subcommand="init", path=str(tmp_path)))

    assert first.value.code == 0
    assert second.value.code == 0
    assert first_content != "stale\n"
    assert first_asset_content != b"stale\n"
    assert all(content != "stale\n" for content in first_tier_contents.values())
    assert readme.read_text(encoding="utf-8") == first_content
    assert asset.read_bytes() == first_asset_content
    assert {
        kind: path.read_text(encoding="utf-8") for kind, path in tier_readmes.items()
    } == first_tier_contents


def test_validate_allows_default_unpaired_warnings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "sdd"
    _write_pair(root)
    unpaired = root / "tales" / "202605" / "legacy.md"
    unpaired.parent.mkdir(parents=True, exist_ok=True)
    unpaired.write_text("# Legacy plan\n", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(_args(path=str(root)))

    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "SDD validation passed" in out
    assert "unpaired-file" in out


def test_validate_strict_fails_unpaired_warnings(tmp_path: Path) -> None:
    root = tmp_path / "sdd"
    (root / "prompts" / "202605").mkdir(parents=True)
    (root / "prompts" / "202605" / "legacy.md").write_text(
        "# Legacy prompt\n", encoding="utf-8"
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(_args(path=str(root), strict=True, quiet=True))

    assert excinfo.value.code == 1


def test_validate_fails_broken_bidirectional_link(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "sdd"
    prompt, plan = _write_pair(root)
    plan.write_text(
        "---\nprompt: sdd/prompts/202605/other.md\n---\n# Plan\n", encoding="utf-8"
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(_args(path=str(root), json=True))

    assert excinfo.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert any(error["code"] == "link-missing-target" for error in payload["errors"])
    assert prompt.exists()


def test_validate_reports_invalid_yaml_frontmatter(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "sdd"
    path = root / "prompts" / "202605" / "bad.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\nplan: [unterminated\n---\n# Bad\n", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(_args(path=str(root), json=True))

    assert excinfo.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["errors"][0]["code"] == "frontmatter-parse"


def test_validate_downgrades_allowlisted_legacy_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.sdd.links as links

    root = tmp_path / "sdd"
    path = root / "prompts" / "202605" / "legacy.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\nplan: sdd/tales/202605/missing.md\n---\n# Legacy prompt\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        links,
        "LEGACY_INVALID_SDD_ERROR_ALLOWLIST",
        frozenset({"prompts/202605/legacy.md"}),
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(_args(path=str(root), json=True))

    assert excinfo.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["errors"] == []
    assert payload["warnings"] == [
        {
            "severity": "warning",
            "code": "link-missing-target-legacy-allowed",
            "path": "prompts/202605/legacy.md",
            "message": "'plan' target does not exist: "
            "sdd/tales/202605/missing.md; "
            "legacy SDD validation error allowlisted",
        }
    ]


def test_validate_does_not_allowlist_other_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.sdd.links as links

    root = tmp_path / "sdd"
    path = root / "prompts" / "202605" / "new.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\nplan: sdd/tales/202605/missing.md\n---\n# New prompt\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        links,
        "LEGACY_INVALID_SDD_ERROR_ALLOWLIST",
        frozenset({"prompts/202605/legacy.md"}),
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(_args(path=str(root), json=True))

    assert excinfo.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "link-missing-target"
    assert payload["warnings"] == []


def test_repair_links_write_backfills_unambiguous_pair(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "sdd"
    prompt = root / "prompts" / "202605" / "fixme.md"
    plan = root / "epics" / "202605" / "fixme.md"
    prompt.parent.mkdir(parents=True, exist_ok=True)
    plan.parent.mkdir(parents=True, exist_ok=True)
    prompt.write_text("# Prompt\n", encoding="utf-8")
    plan.write_text("---\nkeep: yes\n---\n# Epic\n", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(
            _args(sdd_subcommand="repair-links", path=str(root), write=True)
        )

    assert excinfo.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert {action["field"] for action in payload["actions"]} == {"plan", "prompt"}
    assert payload["changed_files"] == [
        "epics/202605/fixme.md",
        "prompts/202605/fixme.md",
    ]
    assert "plan: sdd/epics/202605/fixme.md" in prompt.read_text(encoding="utf-8")
    plan_text = plan.read_text(encoding="utf-8")
    assert "keep: true" in plan_text
    assert "prompt: sdd/prompts/202605/fixme.md" in plan_text


def test_links_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "sdd"
    _write_pair(root)

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(_args(sdd_subcommand="links", path=str(root), json=True))

    assert excinfo.value.code == 0
    rows = json.loads(capsys.readouterr().out)
    assert {row["path"] for row in rows} == {
        "tales/202605/linked.md",
        "prompts/202605/linked.md",
    }
    assert all(row["bidirectional"] for row in rows)


def test_validate_resolves_legacy_plans_link_to_canonical_tales(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sdd"
    prompt = root / "prompts" / "202605" / "linked.md"
    plan = root / "tales" / "202605" / "linked.md"
    prompt.parent.mkdir(parents=True)
    plan.parent.mkdir(parents=True)
    prompt.write_text(
        "---\nplan: sdd/plans/202605/linked.md\n---\n# Prompt\n",
        encoding="utf-8",
    )
    plan.write_text(
        "---\nprompt: sdd/prompts/202605/linked.md\n---\n# Plan\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(_args(path=str(root), quiet=True))

    assert excinfo.value.code == 0


def test_list_invalid_path_exits_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing"

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(
            _args(sdd_subcommand="list", path=str(missing), kind="all", json=False)
        )

    assert excinfo.value.code == 1
    assert "does not exist" in capsys.readouterr().err
