"""Shared real-gate fixtures for Plan Decisions PNG goldens."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.notification_gates.branches import GateBranchData

TALE_CHOICES_PLAN = """\
---
tier: tale
title: Keymap help overlay
goal: Pressing ? shows bindings.
size: small
decisions:
  grouping:
    ask: How should the overlay group bindings?
    choices:
      pane: By pane
      mode: By mode
    default: pane
    why: pane keeps order
  density:
    ask: How dense should the overlay be?
    choices:
      cozy: Cozy spacing
      compact: Compact spacing
    default: cozy
    why: cozy reads better
---
# Plan
Body grouping pane density.
> [!decision] grouping = pane Order by pane.
> [!decision] grouping = mode Order by mode.
> [!decision] density = cozy
Cozy branch.
> [!decision] density = compact
Compact branch.
"""

TALE_MEMORY_PLAN = """\
---
tier: tale
title: Keymap help overlay
goal: Pressing ? shows bindings.
size: small
decisions:
  grouping:
    ask: How should the overlay group bindings?
    choices:
      pane: By pane
      mode: By mode
    default: pane
    why: pane keeps order
  tui_note:
    ask: Record conventions in the tui memory note?
    memory: [tui.md]
    requested: and note the convention in the tui memory note xyz
    default: true
---
# Plan
Body grouping pane tui_note.
> [!decision] grouping = pane Order by pane.
> [!decision] grouping = mode Order by mode.
> [!decision] tui_note
Yes branch.
> [!decision] tui_note = no
No branch.
"""

MEMORY_QUOTE = "and note the convention in the tui memory note xyz"

EPIC_DECISIONS_PLAN = """\
---
tier: epic
title: Overlay program
goal: Ship overlays.
phases:
- id: a
  title: A work unit
  depends_on: []
  size: small
decisions:
  scope:
    ask: Which overlays ship first?
    choices:
      help: Help overlay
      palette: Command palette
    default: help
    why: help is smaller
---
# Plan
Body scope.
> [!decision] scope = help Help first.
> [!decision] scope = palette Palette first.
"""


SYNCTHING_PLAN = """\
---
tier: tale
title: Syncthing legacy tree relocation
goal: Relocate the legacy tree and clean up sync artifacts.
size: medium
decisions:
  root:
    ask: Where should the relocated legacy tree (formerly ~/Sync) live?
    choices:
      db: "~/db: matches the existing $DB/$DBB/$DBH variables in ~/.profile"
      legacy:
        "~/legacy: names it as the pre-chezmoi legacy tree; $DB is repointed at it"
    default: db
    why:
      ~/.profile already calls this root $DB, and a ~/ sibling makes link retargets
      one-component swaps
  dotfiles:
    ask:
      Should the ~70 stow-style dotfile symlinks into the tree become real files in ~?
    choices:
      repoint:
        "No: keep them as symlinks retargeted into the tree (pure rename, lowest risk)"
      materialize:
        "Yes: move each linked file into ~ and rewrite its references; more invasive"
    default: repoint
    why:
      a pure rename fixes everything with one verifiable substitution; de-stowing can
      come later
  conflicts:
    ask:
      Should all ~400 Syncthing *.sync-conflict-* files under ~ (2020-2022) be deleted?
    choices:
      delete:
        "Yes: delete after writing a manifest; copies remain in hercules monthly/yearly
        backups"
      keep:
        "No: keep them (links retargeted); only markers, config, and the package are
        removed"
    default: delete
    why:
      they are Syncthing artifacts by definition, years stale, and still recoverable
      from hercules
  old_tmp:
    ask:
      Should the old 33 GB ~/tmp contents (reachable only via ~/bar) move to
      ~/tmp/old_tmp?
    choices:
      nest:
        "Yes: move them to ~/tmp/old_tmp and delete ~/bar, as the Oct 9 history
        attempted"
      keep: "No: leave them inside the relocated tree and just delete the ~/bar link"
    default: nest
    why:
      zsh history shows `mv ~/old_tmp ~/tmp/` on Oct 9 and `ls ~/tmp/old_tmp` on Oct 12
---
# Plan
Relocate the legacy tree and clean up.
> [!decision] root = db The db branch.
> [!decision] root = legacy The legacy branch.
> [!decision] dotfiles = repoint The repoint branch.
> [!decision] dotfiles = materialize The materialize branch.
> [!decision] conflicts = delete The delete branch.
> [!decision] conflicts = keep The keep branch.
> [!decision] old_tmp = nest The nest branch.
> [!decision] old_tmp = keep The keep branch.
"""


def _exact_length(base: str, length: int) -> str:
    """Pad *base* with filler words to exactly *length* characters."""
    text = " ".join(str(base).split())
    assert len(text) < length, (text, len(text), length)
    counter = 0
    while len(text) < length:
        counter += 1
        piece = f" pad{counter}"
        if len(text) + len(piece) > length:
            text += "x" * (length - len(text))
        else:
            text += piece
    assert len(text) == length, (text, len(text), length)
    return text


def _build_maxcopy_plan() -> str:
    """Five decisions at the grammar limits (lengths asserted, never drift)."""
    id32 = "relocate_legacy_tree_target_xyz1"
    assert len(id32) == 32, len(id32)
    key24 = "delete_after_manifest_ok"
    assert len(key24) == 24, len(key24)
    long_path = "/home/visual/plans/2026/syncthing-migration-manifest-backup.tar.gz"
    assert len(long_path) == 66, len(long_path)
    asks = [
        _exact_length(
            "Where should the relocated legacy tree formerly known as Sync live on this host",
            120,
        ),
        _exact_length(
            "Which cleanup policy applies to every stale synchronization artifact found under home",
            120,
        ),
        _exact_length(
            "Should the compatibility shim stay installed for exactly one more release cycle",
            120,
        ),
        _exact_length(
            "How should the old temporary directory contents move into their nested target",
            120,
        ),
        _exact_length(
            "Record the relocation convention in the shared memory note for later reviewers",
            120,
        ),
    ]
    labels = [
        _exact_length(
            "Keep the tree at the database path matching the existing shell variables file",
            100,
        ),
        _exact_length(
            "Name it as the pre-chezmoi legacy tree and repoint the variable at the new root",
            100,
        ),
        _exact_length(
            "First cleanup choice keeps every artifact in place for review", 100
        ),
        _exact_length(
            "Second cleanup choice stages deletions behind a manifest file", 100
        ),
        _exact_length(
            "Third cleanup choice archives artifacts before removing them", 100
        ),
        _exact_length(
            "Fourth cleanup choice defers the decision to the next review", 100
        ),
        _exact_length(f"Fifth cleanup choice {key24} writes a manifest first", 100),
        _exact_length(
            f"Move them below {long_path} now",
            100,
        ),
        _exact_length(
            "Leave them inside the relocated tree and delete only the link", 100
        ),
    ]
    whys = [
        _exact_length(
            "The profile already calls this root by the short name used everywhere else",
            100,
        ),
        _exact_length(
            "Artifacts by definition stay recoverable from the monthly and yearly backups",
            100,
        ),
        _exact_length(
            "Removing the shim now breaks every pinned plugin still importing it today",
            100,
        ),
        _exact_length(
            "Shell history shows the move was already attempted once on October ninth",
            100,
        ),
    ]
    for ask in asks:
        assert len(ask) == 120, len(ask)
    for label in labels:
        assert len(label) == 100, (label, len(label))
    for why in whys:
        assert len(why) == 100, len(why)
    return f"""\
---
tier: tale
title: Grammar limits stress plan
goal: Hold up at five decisions with every field at its limit.
size: medium
decisions:
  {id32}:
    ask: "{asks[0]}"
    choices:
      db: "{labels[0]}"
      legacy: "{labels[1]}"
    default: db
    why: "{whys[0]}"
  conflicts:
    ask: "{asks[1]}"
    choices:
      keep: "{labels[2]}"
      stage: "{labels[3]}"
      archive: "{labels[4]}"
      defer: "{labels[5]}"
      {key24}: "{labels[6]}"
    default: keep
    why: "{whys[1]}"
  keep_shim:
    ask: "{asks[2]}"
    default: true
    why: "{whys[2]}"
  old_tmp:
    ask: "{asks[3]}"
    choices:
      nest: "{labels[7]}"
      keep: "{labels[8]}"
    default: nest
    why: "{whys[3]}"
  human_only_record:
    ask: "{asks[4]}"
    memory: [tui.md]
    requested: {MEMORY_QUOTE}
    default: true
---
# Plan
Stress the grammar limits.
> [!decision] {id32} = db The db branch.
> [!decision] {id32} = legacy The legacy branch.
> [!decision] conflicts = keep The keep branch.
> [!decision] conflicts = stage The stage branch.
> [!decision] conflicts = archive The archive branch.
> [!decision] conflicts = defer The defer branch.
> [!decision] conflicts = {key24} The manifest branch.
> [!decision] keep_shim
Yes branch.
> [!decision] keep_shim = no
No branch.
> [!decision] old_tmp = nest The nest branch.
> [!decision] old_tmp = keep The keep branch.
> [!decision] human_only_record
Yes branch.
> [!decision] human_only_record = no
No branch.
"""


MAXCOPY_PLAN = _build_maxcopy_plan()


def decision_gate_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    name: str,
    content: str,
    verified_memory: bool = False,
) -> tuple[Path, GateBranchData, list[dict]]:
    """Build real gate data for a decisions golden.

    Writes the plan to tmp and calls ``build_plan_approval_gate_spec``. With
    no artifacts dir a memory quote fails closed to ``quote_not_found`` (the
    unverified case); ``verified_memory=True`` plants the minimal artifacts
    dir (typed root prompt containing the requested quote) for the ``asked``
    case. The spec carries no ``branches`` list, so branches are derived from
    its canonical query exactly as gate creation does.
    """
    from sase.notification_gates.query import parse_gate_query
    from sase.plan_gate import build_plan_approval_gate_spec

    plan = tmp_path / name
    plan.write_text(content, encoding="utf-8")
    if verified_memory:
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir(exist_ok=True)
        (artifacts / "agent_meta.json").write_text(
            json.dumps({"prompt_origin": "typed"}), encoding="utf-8"
        )
        (artifacts / "submitted_prompt.md").write_text(
            f"Please do the work {MEMORY_QUOTE} thanks.\n", encoding="utf-8"
        )
        monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    else:
        monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    spec = build_plan_approval_gate_spec(plan, "visual-session")
    envelope = dict(spec)
    envelope["branches"] = [
        list(branch) for branch in parse_gate_query(spec["query"]).branches
    ]
    gate = GateBranchData.from_envelope(envelope)
    definitions = [
        dict(item)
        for item in spec["payload"].get("decisions", [])
        if isinstance(item, dict)
    ]
    assert definitions, "expected real decision definitions from the gate spec"
    return plan, gate, definitions
