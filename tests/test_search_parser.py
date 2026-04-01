"""Tests for `sase search` parser options."""

from sase.main.parser import create_parser


def test_search_parser_accepts_markdown_format() -> None:
    """`search --format markdown` should parse successfully."""
    parser = create_parser()
    args = parser.parse_args(["search", "status:Ready", "--format", "markdown"])

    assert args.command == "search"
    assert args.query == "status:Ready"
    assert args.format == "markdown"
