---
create_time: 2026-04-17 22:27:29
status: done
prompt: sdd/prompts/202604/fix_bd_new_epic_skill.md
---

# Plan: Fix Stale `bd:new_epic` Slash-Command Skill That Confuses Agents

## Diagnosis (Root Cause)

**Symptom.** When the user invoked the prompt

> #gh:sase Can you help me create one bead for every phase in the plans/202604/repeat_agents_as_entries.md plan file?
> These beads should all be children of a new **plan** bead that you should also create. The plan bead should be linked
> to the plan file using the `sase bead create` command's `--type plan(<plan_file>)` option. …

the previous agent replied with: "No 'epic' type — only `plan` and `phase` are supported types" and "No `--design`
option on `create`". The agent treated the user's (correct) prompt as if it had asked for "epic" + `--design`. The user
never said either of those words.

**Why the agent hallucinated "epic" and "--design".** The Claude harness surfaces a list of available skills in a
system-reminder on every turn. That list contains:

> `bd:new_epic`: Create beads for every phase in a plan file under a new epic

The skill's description and body still describe the **old** bead model:

```
.../home/dot_claude/commands/bd/new_epic.md
---
description: Create beads for every phase in a plan file under a new epic
argument-hint: <plan_file_path>
---

… a new epic bead (make sure this bead has a type of "epic" and not, for example, "feature") …
The epic bead should be linked to the plan file using the `sase bead create` command's `--design` option.
```

Both of these assertions are **factually wrong** against today's CLI:

1. `IssueType` has only `PLAN` and `PHASE` members (`src/sase/bead/model.py:15-17`). "epic" was removed during the
   migration committed in `bf93170b` / `9d7e481f` / `12988234` (see `db.py:62-89` for the one-way migration SQL that
   rewrote `epic → plan` and `child → phase`).
2. `sase bead create --help` shows only `-T/--type`, `-t/--title`, `-d/--description`, `-a/--assignee`. No `--design`.
   `--design` exists only on `sase bead update` (confirmed by reading `cli.py` and running `sase bead update --help`).
3. The correct invocation is `--type plan(<plan_file>)`, as the user's updated prompt already said.

**Why this causes real problems.** Even when the user rewrites the prompt correctly, the stale skill description
("Create beads … under a new epic") is still visible to the agent on every turn. The agent reads the description,
anchors on "epic", and then either (a) ignores the user's corrected terminology, or (b) generates a confused "clarifying
question" that mixes old and new terms, as it did here.

The user has been working around this by hand-editing the prompt every time they invoke `/bd:new_epic`. That work-around
is the signal that the skill is stale.

**Related stale content** (same chezmoi dir, same kind of rot):

- `home/dot_claude/commands/bd/land_epic.md` — title and body refer to "epic bead". Same stale terminology. Command
  itself still works because `sase bead close <id>` is real.
- `home/dot_claude/commands/bd/next.md` — body references the "parent epic bead".

---

## Fix

Two separable concerns:

1. **Content correctness** — `new_epic.md`'s body contradicts the current CLI. This MUST be fixed.
2. **Naming** — the filename `new_epic.md` (which determines the slash-command `/bd:new_epic` and is shown in the skill
   listing) still advertises "epic". This SHOULD be fixed so future agents don't re-anchor on "epic" the moment the
   skill list is rendered.

### Recommended: fix both — update content AND rename files

Rename `new_epic.md` → `new_plan.md` and `land_epic.md` → `land_plan.md`. Fix bodies and descriptions to use `plan` and
`--type plan(<plan_file>)`. Update `next.md` to drop the "epic" reference. Result: the skill list future agents see will
say "Create beads for every phase in a plan file under a new **plan** bead" — aligned with `sase_beads.md` (which
already uses correct terminology — see `src/sase/xprompts/skills/sase_beads.md:14-18`).

Trade-offs considered:

- **Content-only fix (keep `new_epic.md` as the filename).** Smaller change, preserves user's muscle memory of
  `/bd:new_epic`. But the filename is the skill _name_ surfaced to the agent, so the word "epic" still appears in the
  skill list and risks anchoring the agent on the old mental model. The purpose of this fix is to stop the agent from
  being confused by stale terminology; keeping "epic" in the name defeats it.
- **Rename.** Ships a new slash-command name (`/bd:new_plan`, `/bd:land_plan`). User has to update muscle memory once.
  The sase codebase's `sase_beads.md` skill, the `IssueType` enum, the `migrate_beads_to_core.md` plan, and the
  `sase bead create --help` text all use "plan" — this change finishes a migration that's already most of the way done.

Recommendation: **rename**. The user's own corrected prompt already used "plan bead"; aligning the skill name with the
user's current mental model is the point of this fix.

If the user prefers content-only, skip the renames and apply only the body/description edits listed below. The
correctness of the content is what actually unblocks future agent runs — the renames are the anti-regression layer.

---

## Files to Change

All paths below are in the **chezmoi** repo (`/home/bryan/.local/share/chezmoi/`), NOT the sase repo. No sase-repo
changes are needed — the sase-repo skill source file (`src/sase/xprompts/skills/sase_beads.md`) is already correct and
does not need touching.

### 1. Rename `new_epic.md` → `new_plan.md` and rewrite body

Source path: `home/dot_claude/commands/bd/new_epic.md` → `home/dot_claude/commands/bd/new_plan.md`

New contents:

```markdown
---
description: Create beads for every phase in a plan file under a new plan bead
argument-hint: <plan_file_path>
---

Can you help me create one bead for every phase in the @$1 plan file?

These beads should all be children of a new plan bead that you should also create. The plan bead should be linked to the
plan file using the `sase bead create` command's `--type plan(<plan_file>)` option. Also, add the bead ID of the plan to
a new frontmatter field called `bead_id` in the plan file.

Make sure that each phase bead has the appropriate dependencies set up.
```

Changes vs. original:

- `description:` "… under a new epic" → "… under a new plan bead"
- "epic bead" → "plan bead" (all occurrences)
- `--design` option → `--type plan(<plan_file>)` option
- Removed the parenthetical "make sure this bead has a type of 'epic' and not, for example, 'feature'" — `IssueType`
  only has `plan` and `phase` now, there's no "feature" type to disambiguate from.

### 2. Rename `land_epic.md` → `land_plan.md` and rewrite body

Source path: `home/dot_claude/commands/bd/land_epic.md` → `home/dot_claude/commands/bd/land_plan.md`

New frontmatter description: `Close a plan bead after verifying that all the work associated with it is complete.`

Body edits:

- "epic bead" → "plan bead" (all occurrences — lines 2, 13 of current file)
- "AFTER closing the epic bead (some symbols can be ignored while an epic is open)" → "AFTER closing the plan bead (some
  symbols can be ignored while a plan is open)"

No command changes — `sase bead close <id>` (current line 12) is still the right command.

### 3. Edit `next.md` (no rename; terminology fix only)

Source path: `home/dot_claude/commands/bd/next.md`

Body edit:

- "do NOT close the parent epic bead" → "do NOT close the parent plan bead"

No rename needed — the filename `next.md` doesn't contain "epic".

### 4. No changes needed in the sase repo

Confirmed clean:

- `src/sase/xprompts/skills/sase_beads.md` already documents `plan`/`phase` correctly.
- `src/sase/bead/model.py`, `cli.py`, etc. already implement only `PLAN`/`PHASE`.
- Historical plan/spec files under `plans/202603/` and `specs/202603/` mention "epic" (e.g.
  `specs/202603/axe_epic_beads.md`, `plans/202603/epic_approval.md`) but those are **historical design documents** for
  the already-landed migration — they document the old state and the migration rationale. Leave them alone.

---

## Verification

1. From the chezmoi repo root, run `just check` (per `memory/long/external_repos.md`). The chezmoi Justfile has `fmt`,
   lint, and check targets that will format the markdown. Running `just fmt-md` first is fine.
2. After committing to chezmoi, run `chezmoi apply` so the renamed/edited files propagate to `~/.claude/commands/bd/`.
   Per `external_repos.md` this is the **user's** responsibility to trigger — do NOT run it automatically. Flag it in
   the end-of-turn summary.
3. Sanity-check the renames took effect:
   - `ls ~/.claude/commands/bd/` should show `new_plan.md`, `land_plan.md`, `next.md` (and no `new_epic.md`,
     `land_epic.md`).
   - In a fresh Claude session, the skill listing should include `bd:new_plan` with description "Create beads for every
     phase in a plan file under a new plan bead" — no "epic" anywhere.
4. End-to-end smoke: in a fresh session, invoke `/bd:new_plan plans/202604/repeat_agents_as_entries.md`. The agent
   should proceed directly to `sase bead create --title "..." --type plan(plans/202604/repeat_agents_as_entries.md)`
   with no detour through "is there an epic type?".

## Notes on the Failed Run

The user's previous prompt was substantively correct — it had already translated the stale skill template into current
terminology. The fix is to update the template itself so future runs don't have to rely on the user's manual translation
catching every drift between the skill's language and the CLI's language. This is the same pattern as the
`CLI/Skill Contract Synchronization` guidance in `memory/long/generated_skills.md` — skill docs must track the CLI, or
the skill becomes a liability.

## Out of Scope

- Renaming the `bd/` directory itself to `plan/` or similar. The `bd` shortname is still meaningful (it's short for
  "beads") and is not tied to the "epic" terminology.
- Auditing other slash commands outside `bd/` for similar drift. If there's systematic skill/CLI rot, it warrants a
  dedicated audit plan — not bundled into this fix.
- Updating historical design documents under `plans/202603/` / `specs/202603/` — those are a record of the migration,
  not live documentation.
- Any change to the `sase bead` CLI surface. The CLI is already correct; only the skill wrappers are stale.
