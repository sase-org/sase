"""sase's own root bundle fits every capped provider without compaction.

A contract test so ``just check`` runs it for every change set, including a
memory-only edit that contributes no import-graph seeds: growth in sase's
always-inlined memory fails here while it is being authored, before any
capped provider's launch has to compact or fall back. The home layer is an
isolated empty home, so this measures what sase itself ships;
``sase doctor -D -C instructions.bundle_size`` checks real homes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from sase.feature_flags import FeatureFlag, override_flags
from sase.instructions.compaction import delivered_bytes
from sase.instructions.compile import compile_bundle
from sase.instructions.facts import default_facts
from sase.llm_provider.instruction_delivery import capped_root_providers
from tests.instructions.fixture_compiler import write

pytestmark = pytest.mark.contract

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LARGEST_SECTION_COUNT = 8


def _explicit_instruction_flags() -> dict[str, bool]:
    """Enable every provider's explicit-delivery flag so no cap hides."""
    return {
        flag.value: True
        for flag in FeatureFlag
        if flag.value.endswith("_explicit_instructions")
    }


def _largest_sections(sections: Sequence[Mapping[str, Any]]) -> str:
    included = [section for section in sections if section["status"] == "included"]
    included.sort(key=lambda section: (-int(section["length"]), str(section["id"])))
    return "\n".join(
        f"    {section['id']}: {int(section['length']):,} bytes"
        for section in included[:_LARGEST_SECTION_COUNT]
    )


def test_sase_root_bundle_fits_every_capped_provider_without_compaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_INSTRUCTIONS_HOME", str(tmp_path / "ihome"))
    home_root = tmp_path / "empty-home"
    home_root.mkdir()
    config_dir = tmp_path / "global-config"
    write(config_dir / "sase.yml", "{}\n")
    monkeypatch.setattr("sase.config.core.CONFIG_DIR", config_dir)
    monkeypatch.setattr("sase.config.core.get_use_chezmoi", lambda: False)
    with override_flags(**_explicit_instruction_flags()):
        caps = capped_root_providers()
    assert caps, "no provider declares an explicit root max_bytes to gate against"

    problems: list[str] = []
    for provider, cap in caps.items():
        facts = default_facts(_REPO_ROOT, provider=provider, project="sase")
        compiled = compile_bundle(
            facts,
            project_root=_REPO_ROOT,
            home_root=home_root,
            use_cache=False,
            max_bytes=cap,
        )
        size = delivered_bytes(compiled.text)
        if compiled.compaction is None and size <= cap:
            continue
        uncompacted = compile_bundle(
            facts, project_root=_REPO_ROOT, home_root=home_root, use_cache=False
        )
        step = compiled.compaction["step"] if compiled.compaction else "none"
        problems.append(
            f"{provider}: {delivered_bytes(uncompacted.text):,} delivered bytes "
            f"against a {cap:,}-byte cap ({size:,} after compaction step "
            f"{step}); largest sections:\n" + _largest_sections(uncompacted.sections)
        )
    assert not problems, (
        "sase's own root bundle no longer fits a provider cap without "
        "compaction; shrink always-inlined memory (core notes, web rosters) "
        "or move detail into reference memory or strands.\n" + "\n".join(problems)
    )
