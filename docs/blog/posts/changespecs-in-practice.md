---
title: "[06] Patches in Practice — Review State Outside the Chat"
date: 2026-05-20
draft: true
description: >-
  Patches are the durable, reviewable shape of one PR of agent work. They survive the
  chat. Getting Started names them; this post lives inside them.
categories:
  - Agentic Software Engineering
  - Review
slug: changespecs-in-practice
links:
  - Patches: change_spec.md
  - Mentors: mentors.md
  - ACE TUI: ace.md
  - "[05] Commit Workflows — The Pluggable Path From Diff to PR": blog/posts/commit-workflows-plugins.md
  - View on GitHub: https://github.com/sase-org/sase
---

# [06] Patches in Practice — Review State Outside the Chat

Patches are the durable, reviewable shape of one PR of agent work. They survive the
chat. [Getting Started](../../getting_started.md) names them; this post lives inside
them.

<!-- more -->

[\[05\]](commit-workflows-plugins.md) ended with `commit_result.json` — the result
marker written during post-dispatch tracking when `SASE_ARTIFACTS_DIR` is set. The
tracking stage separately creates a Patch for a PR, or appends a stitch to a resolved
Patch for a commit or proposal. This post walks through what's actually in a Patch, how
mentors attach to it, and what the ACE TUI does with it once it exists.

## The ProjectSpec `.sase` Record, End to End

A Patch is a structured block inside a ProjectSpec file at
`~/.sase/projects/<project>/`. Active Patches live in `<project>.sase`; terminal ones
(Submitted, Reverted, Archived) move to `<project>-archive.sase`. Legacy `.gp`
ProjectSpec files from older installs are still readable as a fallback and can be
renamed with `sase patch migrate-extension`; that command changes filenames only, not
the Patch contents. The canonical section order is:

```
NAME: <NAME>
DESCRIPTION:
  <TITLE>

  <BODY>
PARENT: <PARENT>
PR: <PR>
BUG: <BUG>
STATUS: <STATUS>
REFS:
  <REFERENCE_ENTRIES>
STITCHES:
  <STITCH_ENTRIES>
DELTAS:
  <DELTA_ENTRIES>
HOOKS:
  <HOOK_ENTRIES>
COMMENTS:
  <COMMENT_ENTRIES>
MENTORS:
  <MENTOR_ENTRIES>
TIMESTAMPS:
  <TIMESTAMP_ENTRIES>
```

The status lifecycle is a small state machine: `WIP → Draft, Ready`, `Draft → Ready`,
`Ready → Mailed, Draft`, `Mailed → Submitted`. `Submitted`, `Reverted`, and `Archived`
are terminal — the moment a Patch enters one, it moves to the archive file. PR workflows
default new Patches to `Draft` unless `sase commit --status` or `SASE_PR_STATUS`
overrides; manual Patches typically start `WIP`.

## STITCHES, Drawers, and Proposals

Stitches are managed automatically by `sase commit`. Regular commits get sequential
integer stitches `(1)`, `(2)`, `(3)`. A commitless proposal is attached to the latest
regular stitch with a letter suffix such as `(2a)` or `(2b)`; proposals made before the
first regular stitch start at `(0a)`. Proposal entries are flagged with
`(!: NEW PROPOSAL)`. Each stitch can carry zero or more **drawer** lines (6-space
indent, `| ` prefix):

| Drawer | Format                         | Description                                     |
| ------ | ------------------------------ | ----------------------------------------------- |
| `CHAT` | `\| CHAT: <path> (<duration>)` | Agent chat log file with optional run duration  |
| `DIFF` | `\| DIFF: <path>`              | Saved diff file                                 |
| `PLAN` | `\| PLAN: <path>`              | Plan file associated with this stitch (via SDD) |

Those three drawers are how you get back from a Patch to the artifacts an agent
produced. The CHAT drawer's duration (e.g., `2m15s`) is computed from the chat filename
timestamp to the commit time. The PLAN drawer is emitted when `SASE_PLAN` was set during
the commit workflow — i.e., the commit was associated with a tale or epic plan.

## Mentors: What They Actually Do

A **mentor** is a background AI code-review agent. Mentor profiles match commits via
`file_globs`, `diff_regexes`, `amend_note_regexes`, or `first_commit`. When a profile
matches a regular stitch (proposals like `(2a)` are ignored for matching), it is
registered in that stitch's MENTORS entry with `[0/N]` counts. AXE's `mentor_checks`
chop then waits for all non-skipped hooks on that commit to become ready and launches
one background mentor agent per mentor in the profile.

Each mentor runs the `#mentor` xprompt workflow with its role and focus areas, parses
the LLM response as structured JSON, and saves the output under `~/.sase/mentors/`. Each
comment carries `focus_name`, `file_path`, `line_number`, `description`, and one of
three severities (`error`, `warning`, `suggestion`).

Statuses move through:

| Status    | Meaning                                                      |
| --------- | ------------------------------------------------------------ |
| STARTING  | Registered and about to spawn a runner                       |
| RUNNING   | Background mentor runner is active                           |
| PASSED    | Completed successfully with no review comments               |
| COMMENTED | Completed successfully with one or more comments             |
| FAILED    | Execution error or invalid JSON response                     |
| KILLED    | Manually killed or auto-killed because a newer commit exists |
| DEAD      | Runner process disappeared or its PID was reused             |

When a newer commit lands, mentors running against older commits are auto-killed — stale
reviews don't haunt the PR.

## `fix_hook` and `crs`

Two XPrompt workflows live next to mentors:

- **`fix_hook`** — hook-failure remediation. When a hook fails, `fix_hook` launches an
  agent to fix it. Pluggable via tag override, so a project-local or plugin-defined
  `fix_hook` XPrompt overrides the built-in.
- **`crs`** — code-review surfacing. Polls for new review comments and produces critique
  agents that surface what the reviewer flagged. Same tag-override story.

Both are visible in the Agents tab under the `@review` tag alongside mentor agents and
summarize-hook review agents, so review automation can be inspected, killed, dismissed,
or resumed from one side panel.

## HOOKS: The `!` and `$` Prefixes

The HOOKS section records the hook commands attached to this PR. Hook commands are
2-space indented; their run history sits in 6-space-indented drawer lines below:

```
HOOKS:
  just test
      | (1) [260328_143200] PASSED (12s)
      | (2) [260328_153300] FAILED (8s) - (!: Hook Command Failed)
```

Two prefix characters change behavior:

- `!` on a hook command means **failed runs should skip fix-hook hints**. Use it for
  hooks whose failures you would rather investigate by hand than have an agent
  re-attempt.
- `$` on a hook command means **the hook is not run for proposal entries** and is not
  subject to the normal runner limit.

They combine: `!$just presubmit` skips fix-hook hints _and_ skips proposals.

## Advanced ACE Operations

The PRs sub-tab in [ACE](../../ace.md)'s Artifacts tab is built around Patch navigation.
The high-leverage moves:

- **Grouping (`o` / `O`)** cycles the L0 bucket through `BY_PROJECT`, `BY_DATE`, and
  `BY_STATUS`. Sibling workspaces (`foobar_1` / `foobar_2`) share an L1 banner inside
  each L0 bucket.
- **Tree navigation (`<` / `>` / `~`)** walks ancestor / child / sibling PRs. `Ctrl+O` /
  `Ctrl+Shift+O` walk backward and forward through the current-tab jump stack, and
  `` ` `` (backtick) is jump-all across every tab.
- **PR actions** are mostly one-letter: `a` accept proposal, `C` / `c1`–`c9` checkout,
  `d` diff, `e` edit, `f` hooks, `M` mail, `m` mark, `n` rename, `R` rewind, `s` status,
  `Y` sync.
- **Fold modes** (`z` prefix): `z c` cycles STITCHES, `z h` cycles HOOKS, `z m` cycles
  MENTORS, `z t` cycles TIMESTAMPS; uppercase variants toggle between collapsed and
  fully expanded. `z z` cycles every section at once.
- **Mentor review** (`,C`) opens the modal. `Space` toggles acceptance, `a` applies
  accepted comments and proposes (amend), `A` applies accepted comments and commits, `r`
  re-runs a profile, `K` kills the selected running mentor.

The full reference lives in [`ace.md`](../../ace.md). The point is that everything you
would normally do in a code review — find the change, look at the diff, accept or reject
mentor comments, apply changes, advance the status — is keystrokes away from the Patch
record, not from a chat transcript.

## TIMESTAMPS

The TIMESTAMPS section is an auto-maintained audit trail. Each entry has a timestamp, an
event type, and a detail string:

```
TIMESTAMPS:
  [260328_143052] COMMIT  (1)
  [260328_151203] STATUS  WIP -> Draft
  [260328_151510] SYNC    Synced with remote
  [260328_160044] REWORD  Updated description title
  [260328_163012] REWIND  (2)
  [260328_170100] RENAME  old_name -> new_name
  [260328_171500] REBASE  old_parent -> new_parent
```

That trail is what tells you which agent did what when a Patch has been through several.
It is recorded atomically by SASE and is not normally edited by hand.

## What To Read Next

- [Patch format](../../change_spec.md) — every field, every state transition, complete
  examples.
- [Mentors](../../mentors.md) — profile matching criteria, execution lifecycle, ACE
  review modal, apply modes, file-snapshot semantics.
- [ACE TUI](../../ace.md) — the full keybinding reference for the Artifacts, Agents, and
  Axe tabs.
- [\[07\] Driving SASE From Your Phone — Telegram as the Mobile Control Surface](telegram-mobile-agents.md)
  — turn an existing Telegram chat into a two-way control surface for plans, agents, and
  generated artifacts.
