# Memory History

Every committed version of every SASE memory note, web, strand, and agent instruction
file (`AGENTS.md` plus its provider shims, project and home) can be browsed quickly and
understood at a glance. The pager is the single place where history is read: open any
memory file in the pager, press `H` on a Memory panel row, press `C` for the cross-file
changes feed, or run `sase memory history` (`--format json` for agents). Git remains the
only store; a disposable, incremental metadata index provides the speed.

## Concepts

- **Scope.** One owning repository plus the paths that hold memory in it.
  `project:<name>` is the project checkout; `home` is the chezmoi source repo (without
  chezmoi, home has state `NO VCS` and no history).
- **Subject.** A logical document whose identity survives renames: `note:`, `web:` (a
  descriptor note), `strand:` (`web:keyword`), `instructions:` (an `AGENTS.md` plus its
  shim aliases), and `asset:` (non-Markdown, listed only). A provider shim aliases into
  its `AGENTS.md` per version by blob equality; only diverged shim versions are shown
  separately.
- **Version.** One committed state of a subject: ordinal (`v1` is the oldest), commit,
  times, path and blob OID at that commit, change kind, class, summary, provenance
  (agent, bead, subject line), and cause for instruction files.
- **Pseudo-versions.** `STAGED` appears only when the index differs from both HEAD and
  the worktree. The live document is **now**; when the worktree differs from HEAD, now
  is labelled `◌ uncommitted`.
- **Changeset.** One commit's versions across all subjects — the unit of the feed.
  Generated consequences fold under their authored causes.
- **Honest states.** Tracking gaps and dirty states are always visible, never hidden:
  `UNTRACKED`, `IGNORED`, `NO VCS`, `SHALLOW`, `TEMPLATE`, `indexing…`, and
  `history unavailable: <reason>` (fail open to the live document).

## Which version am I reading?

The subject line carries one state pill, in the same place with the same shape in every
state. It is never cropped: as width shrinks it steps through shorter fixed forms
(`⟲ PAST · v24 of 25` → `⟲ PAST · v24/25` → `⟲ v24/25` → `⟲ v24`).

| Pill                  | Meaning                                                                             |
| --------------------- | ----------------------------------------------------------------------------------- |
| `● NOW · v25`         | The live file, clean — identical to the newest version (`≡ v25`)                    |
| `◌ NOW · uncommitted` | The live file with uncommitted or staged edits, on top of `v25`                     |
| `⟲ PAST · v24 of 25`  | A pinned committed version: absolute ordinal of the newest, hidden versions counted |
| `✖ DELETED · v12`     | The subject's newest version is a deletion (tombstone)                              |

Ordinals are absolute and stable: `vK` names the same version in the pill, the picker,
the footer, and `sase memory history -A vK`. Hidden versions (`≈`, `↦`) are skipped
while stepping but never renumbered, so `v24 of 25` stays true.

A clean now **is** the newest version: when the worktree, HEAD, and the newest row
agree, `(` from now steps straight to the version before it instead of landing on a
byte-identical copy labelled past. Untracked, ignored, no-VCS, shallow, template, and
unavailable subjects keep their existing honest chips and never show a pill.

The pill is followed by dim context: `latest · 1mo ago` at now, `on top of v25` (amber)
when dirty, `1mo ago` (violet) in the past, and `Δ v23 → v24` in the diff view — the
base in the delete tone, the target in the insert tone, always reading older to newer.
Past versions also gain a violet gutter rail (`│`) down the full height of the body, so
the past stays visible after the band scrolls away; a deleted subject's rail uses the
muted deleted tone. The footer names where each key goes
(`( v21 · ) now · } now · = diff · @ timeline · E edit now`), and trail crumbs carry
their version (`@v24`, `@v23→v24`, `@✖` for a tombstone, nothing for now).

## Time band anatomy

The `#pager-time` band sits between the trail band and the chrome rule. At now it is a
one-row life strip (scrubber plus history); in the past it is two rows: a timeline row
and a meaning row. A deleted subject shows a tombstone row in chrome, and the body shows
exactly the last content so line numbers still match the file.

```text
 ▤ sase/memory/gotchas.md  [⟲ PAST · v24 of 25]  1mo ago                                   100% · ⌘ 1.7Kc · md
 ⇧ promoted reference → core · § Default Keymap Config · +31w −4w      sase-1au.5 · athena.… · 1a2b3c4
 ▁▁▃▁▂▁▇▁▁▂▅▁▁▃▁▂▁▁▅▁▂▁▃▁▆▂▁▃▁▂▁▅▁█▁▂▏▁▂ → now   Sep 22 2026 14:03 · v24 · 1 newer · ⇡2 on origin/master
```

- **Playhead scrubber.** One cell per version (bucketed past the width): bar height is
  the log-scaled words changed (`▁▂▃▄▅▆▇█`). The open version is the bright playhead
  cell; hidden versions are dim `·`. Labelled ends name the oldest and newest stops, so
  you can see where you sit in the file's life.
- **Timeline row.** Scrubber plus absolute date and time, the version (`v24`), how many
  versions are newer, and `⇡N on origin/<default>` when behind the remote. Shedding
  order: the commit subject, the `⇡N` marker, the newer count, the weekday and time (the
  date stays), then the scrubber down to 8 cells.
- **Meaning row.** Class glyph, section path, word delta, frontmatter semantics; on the
  right, provenance: bead, agent, short SHA. Each is a jump-label target: the bead opens
  the bead, the agent opens its chat, and the commit opens the commit view (or copies
  when no resolver exists).
- **Past tint.** While pinned in the past, the band gets a faint violet tint and the
  body rail turns violet. Past is violet, never amber — amber already means uncommitted.
  Every history colour comes from the theme-aware palette, so the past stays legible in
  dark and light themes.
- **Instruction subjects** get a cause row instead:
  `⟳ rendered · sources: gotchas.md · dispatch.md` (each source opens that note at the
  same commit in the diff view), `⚙ config change`, `⚙ regenerated`, or `◆ hand-edited`,
  with a `CLAUDE.md ≡ AGENTS.md` / `⚠ diverged` chip.
- **Degradation.** The band sheds rows and fields as space shrinks, and at 12 rows or
  fewer it folds away — the pill context then gains the short date (`Aug 24 · 1mo ago`)
  because the band's absolute date is off screen. Chrome never pushes or wraps the body.

## Keys

All time keys are punctuation, so the jump-label alphabet is untouched. Small motions
(`(`, `)`, `{`, `}`) push nothing onto the trail; jumps (picker opens, feed links, band
links, links followed from a past version) push a trail entry that records its version
pin, so Backspace returns to the exact moment.

| Key       | Action                                                                                                    |
| --------- | --------------------------------------------------------------------------------------------------------- |
| `(` / `)` | Older / newer version (hidden versions skipped; `)` from the newest committed version returns to **now**) |
| `{` / `}` | First version / back to now (tombstone for a deleted subject)                                             |
| `=`       | Switch between the **read** and **diff** views (sticky)                                                   |
| `@`       | Open the timeline picker                                                                                  |
| `[` / `]` | Previous / next change, in either view                                                                    |

The footer names each time key's destination
(`( v21 · ) now · } now · = diff · @ timeline · E edit now`) and shows a verb only when
its key would do something; the rest are under `?` in the "Time" group, which also
carries a four-pill legend. Search (`/`) persists across versions. `yy` copies
`sha:path` in the past, or a unified diff in the diff view. `E` always edits **now** —
pinned it reads `E edit now`, otherwise `E edit`, never both. `r` refreshes, re-syncs
the index, and follows HEAD.

**Timeline picker (`@`).** An aligned table over all versions that never wraps: a
two-cell marker column (`●` marks the open version, `▸` the cursor), ordinal, age and
date, class glyph, change, and attribution columns. `now` is always listed (with an
`≡ now` alias when the worktree matches the newest version), plus a hidden-versions
summary row. `j`/`k`/`g`/`G` move, `⏎` opens and pushes a trail entry, `=` compares the
highlighted row with the open version (always reading older to newer), `.` toggles
hidden versions, `/` filters across section, agent, bead, and words. The footer previews
what `⏎` and `=` will do from the cursor. Rows render lazily, so long timelines open
instantly.

**Diff view (`=`).** Inline word insertions and struck-through deletions with
reflow-insensitive word diffing, a frontmatter semantic block (for example
`⇧ type: reference → core`), and folds of unchanged runs that expand in place from a
label. By default the diff compares against the parent version (worktree against HEAD
when dirty); the picker's `=` sets any other base. Arriving from the feed, a cause link,
a band source link, or `-d` opens the diff view; arriving from a note, the Memory panel,
or a plain file opens the read view.

**Changes feed.** `sase memory history` with no selector, or `C` in the Memory panel:
one section per day, each changeset listing its authored subjects as labels that open
`subject@version` in the diff view. Generated consequences fold under their cause,
regen-only changesets collapse into an expandable count, home changes interleave tagged
`⌂`, and `r` resyncs.

## Glyphs

One vocabulary everywhere — CLI, band, picker, feed, and Memory panel:

| Glyph   | Meaning                                   | Default in a timeline                         |
| ------- | ----------------------------------------- | --------------------------------------------- |
| `✚`     | Created (or recreated after a gap)        | shown                                         |
| `◆`     | Authored edit                             | shown                                         |
| `⇧`/`⇩` | `type` promoted / demoted                 | shown, highlighted                            |
| `▣`     | Frontmatter-only                          | shown, dim                                    |
| `⟳`     | Regenerated or rendered                   | shown for those subjects; folded in the feed  |
| `⚙`     | Config- or renderer-driven, or regen-only | shown, with its cause                         |
| `≈`     | Reflow or whitespace-only                 | hidden (dim dot in the sparkline)             |
| `↦`     | Pure move or rename                       | hidden (path change shows in band and picker) |
| `✖`     | Deleted                                   | shown, as a tombstone                         |
| `◌`     | Uncommitted or staged (amber)             | shown when dirty                              |
| `⇡N`    | N newer versions on `origin`              | marker only                                   |

Hidden versions (`≈`, `↦`) show with `-a/--all`. A deleted subject shows its last
content exactly as committed — the deletion notice lives in chrome (the `✖ DELETED` pill
and a band tombstone row), never as a body line, so line numbers still match the file.

## CLI

```bash
sase memory history                        # changes feed (pager on a TTY)
sase memory history gotchas.md             # timeline for a note
sase memory history sase/memory/tui.md     # repo-relative path also works
sase memory history glossary:stitch        # strand by web:keyword
sase memory history AGENTS.md -d           # instruction change as a diff
sase memory history tui.md -A v7           # one version with its body
sase memory history tui.md -f json         # Rust wire unchanged, for agents
sase memory history -S home --since 2026-09-01 -l 20
```

Selectors accept flat names, repo-relative paths, bare web names, `web:keyword` strands
(with alias lookup), instruction paths (`AGENTS.md`, `CLAUDE.md`, `~/AGENTS.md`, …), and
historical names (`build_and_run.md` resolves to the renamed subject, with a notice).
Options: `-a/--all`, `-A/--at REV` (`v7`, `~2`, SHA prefix, or date), `-d/--diff`,
`-f/--format {json,pager,text}` (pager on a TTY, else text), `-l/--limit N`,
`-p/--project REF`, `-s/--since DATE`, `-S/--scope {all,home,project}`. Viewing history
never writes a read-audit event.

## What is and is not tracked

- **Git is the only store.** Uncommitted worktree and staged states appear as honest
  pseudo-versions labelled "not durable until committed". Overwritten intermediate saves
  that were never committed cannot be recovered.
- **Scope is SASE memory only.** Provider-native memories (for example Claude Code's
  per-project memory directories) are out — SASE neither writes nor versions them.
- **Home history is the chezmoi template source**, shown with a `TEMPLATE` chip.
  Deployed `~/sase/memory/*` and `~/AGENTS.md` map to their chezmoi source subjects.
- **Read-only.** There is no restore in v1.
- **Links from past versions resolve at that past revision.** If a target did not exist
  at that revision, the pager says so instead of falling back to today's file.

` sase memory init --check` fails on untracked or ignored managed memory and instruction
files, and publish fails loudly instead of reporting success when an intended file was
not committed.

## Performance

Targets below are design goals; the numbers next to them are current measurements on the
sase repo. Gaps are known follow-up work, not regressions to chase here.

- First paint is unchanged for every pager document: history loads after paint while the
  band shows `indexing…`, and a time key pressed while loading runs as soon as the data
  arrives.
- Warm version step: p95 ≈ 6 ms from key press to paint against a 30 ms target (met).
  Stepping reuses the prefetched blob, comparison, and repaint, so no git or file IO
  happens on the keystroke or render path.
- Warm freshness check / per-query: ≈ 45–90 ms against a 30 ms target. A warm timeline
  query currently costs around 55–60 ms; narrowing that gap means fewer git probes per
  query.
- Cold index build: ≈ 2.3 s against a 1.5 s target, measured off-thread with shims and
  classification. Incremental updates over recent commits stay near instant.
- CLI end to end: `sase memory history gotchas.md -f text` completes in ≈ 1.7 s.
  Interpreter and CLI start-up dominate that number (≈ 1.4 s of it); the history query
  itself is a fraction of a second.
- Optional git maintenance speeds up cold builds:
  `git commit-graph write --changed-paths` and Git ≥ 2.51. SASE only suggests this and
  never runs it automatically.
