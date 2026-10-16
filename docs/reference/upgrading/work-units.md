---
title: Work unit migration notes
description: Compatibility notes for bead, plan, Patch, and ProjectSpec formats.
---

# Work unit migration notes

This page collects format changes that affect older work-unit records.

## ProjectSpec Extension

ProjectSpec files with the `.gp` extension remain readable. Run
`sase patch migrate-extension` to rename them to `.sase`; the command changes filenames
without rewriting Patch blocks or review state.

## Plan Frontmatter

Plan links now use `PARENT` and `PROMPT` Markdown bullets. The `parent:` property
remains accepted with a deprecation warning; `sase plan links refresh --write` moves it
into a `PARENT` bullet. `sase plan links repair --write` converts `plan:` and `prompt:`
properties into canonical bullets and removes the matching property. Reads and
validation leave those properties unchanged.

## Patch Fields

New Patch blocks use `STITCHES:` and `PR:`. Existing `COMMITS:` and `## ChangeSpec`
headers remain readable and are preserved during unrelated edits. `CL:` remains accepted
and is rewritten as `PR:` when the Patch is touched.

## Bead Note Recovery

`sase bead history --lost-notes` finds notes dropped by old whole-field updates;
`--restore` appends recoverable text as new attributed notes.

## Related

- [Work units](../work-units/index.md) — current bead, plan, Patch, and ProjectSpec
  behavior.
- [Upgrading](index.md) — all upgrade and history notes.
