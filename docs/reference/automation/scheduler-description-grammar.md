---
title: Scheduler description grammar
description: The grammar and style rules for scheduler routine descriptions.
---

# Scheduler description grammar

This page describes how scheduler routine descriptions are structured.

## Description Grammar

Both `axe.routines.<name>.description` and every job `description` use one grammar,
borrowed from the shape of a Git commit message:

```
<summary>
<blank line>
<body…>
```

- Line 1 is the **summary**: non-blank, at most 100 characters, no leading or trailing
  whitespace.
- If anything follows the summary, line 2 **must be blank**. That single rule makes the
  split unambiguous.
- Everything from line 3 on is the **body**: free-form prose. Blank lines separate
  blocks, and a block whose first line starts with `-`, `*`, or `•` is rendered as a
  bullet list.
- The whole description is at most 2000 characters.
- A single-line description is still completely valid and simply has an empty body.

Service proc descriptions use the same grammar for display, are not shape-validated, and
have their body start at line 2 when the blank separator is missing.

The split is owned by the shared Rust config authority (`split_axe_description`), so the
sase's TUI Services tab, both CLI listings, and the entry editor always agree on where
the summary ends. It is computed once per entity when the config is parsed, never on a
render or keystroke path.

Author multi-line descriptions as YAML literal block scalars (`|-`), hand-wrapping
source lines to keep the file inside the configured Markdown prose width
(`markdown.print_width`, `88` by default):

```yaml
description: |-
  Complete finished hooks and start stale ones, with zombie detection

  Scans every Patch matching the axe query, completes hooks whose runner exited, and starts the next
  stale hook when a runner slot is free.

  - Honors max_hook_runners; a full slot table defers work to the next tick rather than queueing.
  - Hooks still running past zombie_timeout_seconds are marked ZOMBIE and stop holding a slot.
```

Hard wraps in the source are stored verbatim, and the renderer reflows: consecutive
non-blank, non-bullet lines in a block are joined with single spaces and re-wrapped to
the available width. A description authored at 110 columns therefore still fills a
200-column pane and still reads correctly at 60.

### Diagnostics

Shape violations are reported by the config authority with `severity: "error"` at the
offending field's config path. At most one code is emitted per description, checked in
this order:

| Code                                  | Condition                               | Message                                                                     |
| ------------------------------------- | --------------------------------------- | --------------------------------------------------------------------------- |
| `description_summary_blank`           | line 1 is empty or whitespace-only      | `description must start with a non-blank summary line`                      |
| `description_summary_too_long`        | the summary exceeds 100 characters      | `description summary line must be at most 100 characters (found <n>)`       |
| `description_body_separator_required` | a line 2 exists and is not blank        | `description must leave line 2 blank to separate the summary from the body` |
| `description_too_long`                | the description exceeds 2000 characters | `description must be at most 2000 characters (found <n>)`                   |

A blank description is still reported as `blank_value`, and a missing one as
`required_missing`, exactly as before. The four shape checks are gated behind a
`require_description_shape` request flag that defaults to off on the wire; SASE turns it
on for both config composition and AXE entry edits, so they always apply to configs SASE
loads.

### Authoring Style Guide

**Summary (line 1)**

- One line, at most 100 characters, target 80. Sentence case, no trailing period.
- Present tense, active voice, describing what the entity _does_, not what it is.
- Must stand alone: the collapsed Services-tab panel, both CLI listings, and the entry
  editor's preview show only this line.

**Body**

- One to three short paragraphs and/or one bullet list. Aim for six to ten rendered
  lines.
- Answer, in this order, only what is true and non-obvious: what it actually does, when
  it fires, what state it reads or mutates, and the one thing an operator most needs to
  know (a failure mode, a safety property, a cost, a limit).
- Name the config knobs that matter when they are set (`interval`, `job_timeout`,
  `run_every`, `trigger`, `inhibit_if`, `for_each`, `env`).
- Do not restate the summary, do not narrate the implementation line by line, and do not
  document SASE concepts that belong elsewhere in `docs/`.

**Routine bodies additionally** state the cadence in words and why that cadence is right
for the lane, and say what belongs in the lane and what deliberately does not, so a
reader knows where to add a new job.

**Mechanics**: bullets start with `- ` at the block's base indentation and continuation
lines indent two further spaces; no trailing whitespace, no tabs, and no blank line at
the end of the block.

## Related

- [Scheduler configuration](scheduler-configuration.md)
- [Scheduler jobs](scheduler-jobs.md)
