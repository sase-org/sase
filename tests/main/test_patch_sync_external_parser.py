from __future__ import annotations

from sase.main.parser import create_parser


def test_patch_sync_external_parser_options() -> None:
    parser = create_parser()

    args = parser.parse_args(
        ["patch", "sync-external", "--dry-run", "--full", "--project", "sase"]
    )

    assert args.command == "patch"
    assert args.patch_subcommand == "sync-external"
    assert args.changespec_subcommand == "sync-external"
    assert args.dry_run is True
    assert args.full is True
    assert args.project == "sase"
