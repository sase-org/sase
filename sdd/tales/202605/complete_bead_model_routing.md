---
create_time: 2026-05-10 01:01:05
status: wip
prompt: sdd/prompts/202605/complete_bead_model_routing.md
---
# Plan: Complete Bead Model Routing Verification

## Context

The prior phase agents reported `sase-2o.1` through `sase-2o.5` as implemented and closed, but the current checkout
still has all beads open and no `sase-2o` implementation commits. The sibling Rust core repo contains uncommitted
bead-model work, while the Python repo is missing the public `model` field, CLI flags, wire conversion, mobile
projection, and work-prompt rendering.

## Steps

1. Integrate Python bead `model` support end to end: dataclass, validation, legacy SQLite/JSONL helpers, Rust facade
   conversion, create/update facade arguments, and mobile bead summary/detail projection.
2. Expose the field through CLI create/update/show and update focused tests for parser, create/update/show, validation,
   JSONL/DB compatibility, and mobile helpers.
3. Finish work-plan rendering support by carrying phase, epic land, and legend land models through Python work
   dataclasses and emitting `%model:<value>` only on configured segments.
4. Update built-in bead prompt guidance and the `sase_beads` skill source, then regenerate generated skills with
   `sase init-skills --force` and apply them.
5. Verify with focused Python tests, Rust bead tests in `../sase-core`, `just install`, and `just check`.
6. Close child beads and the epic bead, then run `just pyvision` after the epic is closed.
7. Mark `sdd/epics/202605/bead_model_routing.md` frontmatter `status: done`.
