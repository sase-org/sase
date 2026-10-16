---
title: "Display and reading configuration"
description: "Configuration for Markdown rendering, paging, and reading surfaces."
---

# Display and reading configuration

Configuration for Markdown rendering, paging, and reading surfaces.

## markdown

The column width SASE wraps generated Markdown prose at. It governs every Markdown
surface SASE writes or renders itself: plan files, bead notes and pages, memory shims
and the generated `AGENTS.md`/provider instruction files, generated skills, prompt
archives, SDD documents, and the default `--wrap` for `sase bead show` and
`sase plan show`. The value is resolved on each call, so an edit takes effect on the
next command without restarting anything.

Values below the minimum, of the wrong type, or in a malformed config fall back to the
shipped default rather than raising: a broken `sase.yml` must never turn
`sase plan propose` into a traceback.

```yaml
markdown:
  print_width: 88
```

[Generated reference for `markdown`](runtime.md#markdown)

The minimum of `20` is the floor below which SASE's display wrapper stops wrapping
entirely, so a smaller value would silently do nothing.

**Sharp edge: the prettier CLI cannot read this field.** `prettier` (via `just fmt-md`,
CI, or an editor integration) discovers its configuration from files on disk — a repo's
`package.json`, `.prettierrc`, and friends — and those declarations mirror SASE's
_shipped default_, not your effective configured value, so that a stock checkout is
self-consistent for a contributor with no SASE config at all. If you configure a
non-default `markdown.print_width` and then run `sase init` inside a repo whose prettier
config still declares the default, the regenerated `AGENTS.md` will be wrapped at your
width and that repo's `fmt-md-check` will fail on it. Change the repo's prettier config
to match, or leave the field at its default.

## pager

File-aware syntax highlighting for the SASE pager. Eligible raw sources — files,
Markdown documents, diffs, and stdin with a convincing diff prefix — receive a muted
language-aware overlay after first paint. Formatted cards, bead detail, commit
manifests, and producer-styled ANSI stay unhighlighted.

```yaml
pager:
  syntax: auto
```

[Generated reference for `pager`](runtime.md#pager)

CLI `--syntax` overrides this field. `--syntax none` and `--color never` disable the
added layer for the rest of the session, including followed targets. Unknown values fail
schema validation (`sase config` / doctor diagnostics) and the runtime accessor falls
back to `auto` so a hand-edited `sase.yml` cannot crash the pager.

## Related

- [Runtime and stored data configuration](runtime.md) — generated reading-surface keys.
- [SASE Pager](../../pager.md) — pager behavior.
