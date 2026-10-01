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

## Time band anatomy

The `#pager-time` band sits between the trail band and the chrome rule:

```text
 ◆ sase/memory/gotchas.md                                  ⟲ PAST v8/9 · 8 days ago · 34% · md
 ⇧ promoted reference → core · § Default Keymap Config · +31w −4w      sase-1au.5 · athena.… · 1a2b3c4
 ▁▁▃▁▂▁▇▁▁▂▅▁▁▃▁▂▁▁▅▁▂▁▃▁▆▂▁▃▁▂▁▅▁█▁▂ → now ◌              Sep 22 2026 14:03 · ⇡2 on origin/master
```

- **Subject chip.** In the past: `⟲ PAST v8/9 · 8 days ago` in the violet past accent.
  At now: `⟲ 9 versions` (dim), or amber `◌ uncommitted` when dirty. Past is violet,
  never amber — amber already means uncommitted.
- **Meaning row.** Class glyph, section path, word delta, frontmatter semantics; on the
  right, provenance: bead, agent, short SHA. Each is a jump-label target: the bead opens
  the bead, the agent opens its chat, and the commit opens the commit view (or copies
  when no resolver exists).
- **Time row.** Sparkline plus absolute date and time, ending with `→ now`, `◌` when
  dirty, and `⇡N on origin/<default>` when behind the remote.
- **Sparkline.** One cell per version (bucketed past the width): bar height is the
  log-scaled words changed (`▁▂▃▄▅▆▇█`). Promotions use the past accent, deletions the
  error colour, regenerations dim, hidden versions dim `·`, and the current cell reverse
  video.
- **Instruction subjects** get a cause row instead:
  `⟳ rendered · sources: gotchas.md · dispatch.md` (each source opens that note at the
  same commit in the diff view), `⚙ config change`, `⚙ regenerated`, or `◆ hand-edited`,
  with a `CLAUDE.md ≡ AGENTS.md` / `⚠ diverged` chip.
- **Degradation.** The band sheds rows and fields as space shrinks: the time row drops
  on short screens, the meaning row sheds SHA, agent, bead, then section path as width
  shrinks, and at 12 rows or fewer the band folds into the subject chip. Chrome never
  pushes or wraps the body.

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

The footer shows only `( ) version · = diff · @ timeline · } now` when they apply; the
rest are under `?` in the "Time" group. Search (`/`) persists across versions. `yy`
copies `sha:path` in the past, or a unified diff in the diff view. `E` always edits
**now**. `r` refreshes, re-syncs the index, and follows HEAD.

**Timeline picker (`@`).** A modal over all versions including worktree and staged rows
plus a hidden-versions summary row. `j`/`k`/`g`/`G` move, `⏎` opens and pushes a trail
entry, `=` compares the highlighted row with the open version (two-point compare), `.`
toggles hidden versions, `/` filters across section, agent, bead, and words. Rows render
lazily, so long timelines open instantly.

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
content under a muted-red tombstone rule.

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

- First paint is unchanged for every pager document: history loads after paint while the
  band shows `indexing…`, and a time key pressed while loading runs as soon as the data
  arrives.
- Warm version steps complete within 30 ms from key press to paint (prefetched blob,
  comparison, repaint). No git or file IO happens on the keystroke or render path.
- Index, measured on the sase repo: cold build with shims and classification within 1.5
  s off-thread, incremental update over 100 commits within 100 ms, warm freshness check
  within 30 ms.
- `sase memory history <note>` against a warm snapshot completes within 300 ms end to
  end.
- Optional git maintenance speeds up cold builds:
  `git commit-graph write --changed-paths` and Git ≥ 2.51. SASE only suggests this and
  never runs it automatically.
