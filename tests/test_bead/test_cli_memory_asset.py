"""CLI contract coverage for examples in generated bead memory."""

from __future__ import annotations

import re
import shlex

from sase.main.parser import create_parser
from sase.mdtemplates import packaged_markdown_text


def test_generated_bead_memory_examples_parse_against_cli_contract() -> None:
    source = packaged_markdown_text(
        "sase.main.init_memory",
        "templates/memory-sase-beads.template.md",
    )
    examples: list[str] = []
    in_bash_fence = False
    for line in source.splitlines():
        if line.strip() == "```bash":
            in_bash_fence = True
            continue
        if line.strip().startswith("```"):
            in_bash_fence = False
            continue
        if in_bash_fence and line.startswith("sase bead "):
            examples.append(line)

    assert len(examples) == 4
    parser = create_parser()
    for example in examples:
        example = example.replace("<size>", "small")
        concrete = re.sub(r"<[^>]+>", "example", example)
        args = parser.parse_args(shlex.split(concrete)[1:])
        assert args.command == "bead"
