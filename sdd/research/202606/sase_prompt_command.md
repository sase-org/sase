---
create_time: 2026-06-13
updated_time: 2026-06-13
status: research
---

# `sase prompt` Command Research

## Research Request

Would a new top-level `sase prompt` command — for managing previously-used sase agent prompts from the command line —
be useful? If so, what functionality should it provide? Recommendations should be ambitious but practical: every
proposed feature must map to a real, objective use-case.

## Bottom Line

Yes. SASE already *records* every launched prompt but offers no command-line way to **inspect, search, reuse, prune, or
curate** that history — the only doors into it are the interactive TUI modal and an `fzf`-gated picker hidden behind
`sase run .`. Meanwhile the backing file has grown unbounded to **9,064 entries / ~32.5 MB** and is fully rewritten
(read → parse → rewrite → `fsync`) on *every* agent launch.

A `sase prompt` command should do two things:

1. **Expose prompt history to the shell** the way `sase chats` already exposes transcripts — `list`, `search`, `show`,
   `stats` with a stable `--json` schema, so history is greppable, pipeable, and scriptable.
2. **Give history a lifecycle** — `rm`, `prune`, and a bridge (`save --as`) that promotes a frequently-reused history
   entry into a curated, file-backed **xprompt**. Today a prompt you have run 40 times stays a transient line forever;
   there is no path from "I keep retyping this" to "this is now `#my-prompt`".

Recommended command surface (mirrors the existing `sase chats` precedent):

```
sase prompt list   [-j] [-l N] [-q SUBSTR] [--cancelled | --all]   # recency-sorted, scriptable
sase prompt search QUERY [-j] [-l N]                               # sugar over `list -q`
sase prompt show   SELECTOR [-j]                                   # full text to stdout
sase prompt stats  [-j]                                            # counts, size, cancelled rate, top refs
sase prompt rm     SELECTOR [-y]                                   # delete one entry (also: secret scrub)
sase prompt prune  [--before DATE] [--keep N] [--cancelled] [--dedup] [--dry-run]
sase prompt save   SELECTOR --as NAME [--project P] [--tag T...]   # promote history entry -> xprompt
```

Plus one **ambitious architectural recommendation**: move prompt-history *storage* into the Rust `sase-core` backend
(SQLite-backed, atuin-style), since a CLI is exactly the cross-frontend trigger the
`rust_core_backend_boundary` rule was written for. This is a separate, optional track; the CLI above works on the
current JSON store with only a cap/prune added.

## Evidence: Current State

### There is no `sase prompt` command today

Top-level subcommands are registered in `src/sase/main/parser.py` (`register_*_parser(top_level_subparsers)`) and
dispatched in `src/sase/main/entry.py` (`if args.command == "...":`). There is no `prompt` entry in either. The token
`"prompt"` in `parser_commands.py:485` is only the **positional argument** of `sase run`, not a subcommand.

### Prompt history *is* already captured — silently

- Storage: `src/sase/history/prompt.py`, persisted to `~/.sase/prompt_history.json`.
- Model: `PromptEntry(text, branch_or_workspace, timestamp, last_used, workspace, cancelled)`; dedup key is **exact
  prompt text** (`_apply_prompt_mutations`, prompt.py:293).
- Write API: `add_or_update_prompt()` — skips prompts shorter than 2 words unless `allow_short=True`; only *upgrades*
  cancelled→non-cancelled, never downgrades.
- It is written from **five** launch paths:
  `src/sase/ace/tui/actions/agent_workflow/_launch_body.py`, `.../_prompt_bar_mount.py`,
  `src/sase/agent/launch_cwd.py`, `src/sase/main/query_handler/_query.py`, and `prompt.py` itself.

### Two problems the current design has, measured on the live store

1. **Unbounded growth.** `prompt.py` has **no cap and no prune** (unlike `vcs_xprompt_mru.py`, which caps at 100). The
   live file is **9,064 entries, ~32.5 MB, 723 of them cancelled**. Nothing ever removes anything.
2. **A 32 MB read-modify-write on the launch hot path.** Each launch calls `_load_prompt_history_for_write()` (parse all
   32 MB) → mutate → `_save_prompt_history()` (serialize all entries, `fsync`, atomic `os.replace`) under an exclusive
   `flock`. This directly tensions with the `tui_perf` rule ("no synchronous disk I/O on hot paths") and gets linearly
   worse as the file grows. A `sase prompt prune` (and an eventual cap) is not a nicety — it is overdue maintenance.

### The only ways to *reach* history today are interactive and hidden

- **TUI modal** (`src/sase/ace/tui/modals/prompt_history_modal.py`): leader `,.` and `,>` (cancelled). Rich, but
  TUI-only.
- **CLI `fzf` picker** (`show_prompt_history_picker` in `src/sase/main/query_handler/_editor.py`): reachable *only* by
  typing `sase run .` or `sase run "#gh:sase ."` (`special_cases.py:99`). It hard-requires `fzf`, always opens `$EDITOR`,
  and immediately *executes* the result. There is **no read-only / non-`fzf` / `--json` / grep-able** access at all.

So history is write-mostly: easy to accumulate, hard to introspect, impossible to script.

### An in-flight epic changes the data model — design against its target

`sdd/epics/202606/prompt_history_tui.md` (bead `sase-4m`, WIP) makes history **recency-only**: it removes
branch/workspace/project ranking, the `*`/`~` markers, and the `sort_by`/`current_branch`/`current_workspace` picker
args, and narrows persisted fields to `text`, `timestamp`, `last_used`, `cancelled` (legacy fields read-compatible).
**`sase prompt` must be designed against this post-epic recency-only model**, and should land after or alongside it —
otherwise it would bake in ranking semantics that are being deleted.

### Related stores `sase prompt` should be aware of (but not absorb)

| Store | File | Capped? | Surface today |
| --- | --- | --- | --- |
| Prompt history | `~/.sase/prompt_history.json` | **No** | TUI modal, `sase run .` |
| Background command history | `~/.sase/command_history.json` | No (dedups) | TUI command picker |
| VCS xprompt MRU | `~/.sase/vcs_xprompt_mru.json` | Yes (100) | `Ctrl+P/Ctrl+N` cycle |
| Chat transcripts | `~/.sase/chats/*.md` | No | `sase chats list/show` |
| xprompts (curated) | `~/.xprompts/*.md`, project `xprompts/`, … | n/a | `sase xprompt list`, `#name` |

Keep `sase prompt` focused on **prompt history**; the others have their own homes. The one bridge worth building is
history → xprompt (see Recommendation §3).

### The natural precedent to copy: `sase chats`

`sase chats` (`src/sase/chats/cli_list.py`, `parser_chats.py`) already solves the identical "expose a recency log to the
shell" problem: `list` with `-j/--json` (stable schema), `-l/--limit` (default 20), `-q/--query` (case-insensitive
substring); `show` with selectors and `--format`; a Rich table by default. `sase prompt` should match this shape
verbatim so the two commands feel like siblings.

## Prior Art

- **atuin** (the gold standard for "manage shell history from the CLI"): replaces flat history with a **SQLite** store
  and adds full-screen search, filtering (session/dir/global, time range, exit code), and a much-loved **`atuin stats`**
  (most-used commands/patterns). Lessons: (a) a structured backing store makes search/stats cheap and avoids
  rewrite-the-world on every append; (b) **stats** is a feature, not an afterthought; (c) sync/encryption is valuable
  but is its own large subsystem — defer it.
- **Prompt-management CLIs / prompt libraries** (PMC, `prompt-management/cli`, PromptHub): YAML/Markdown storage,
  metadata/tag filtering, and Git-style versioning of *named* prompts. SASE already has this layer — it is called
  **xprompts**. The gap is not a new library format; it is the **promotion path** from ad-hoc history into that library.
- **OpenAI deprecating reusable *prompt objects*** (June–Nov 2026): reinforces that the durable approach is
  **file-backed, version-controllable** prompts (i.e. xprompts in git), not an opaque managed object. The bridge should
  write real `.md` files, not a proprietary blob.

## Use-Case → Feature Map

Every proposed feature below is justified by a concrete, observed need — not speculation.

| # | Real, objective use-case | Feature |
| --- | --- | --- |
| 1 | "What have I asked agents to do lately?" — history is invisible outside the TUI. | `prompt list` |
| 2 | "I ran a great refactor prompt last week; find it without `fzf`/`$EDITOR`." | `prompt search` / `list -q` |
| 3 | "Re-run / pipe a past prompt in a script: `sase run "$(sase prompt show 3)"`." | `prompt show` (stdout, `--json`) |
| 4 | "Which prompts/workflows do I actually use? How big is this file? What's my cancel rate?" | `prompt stats` |
| 5 | "I pasted a token into a prompt — scrub that one entry now." (security) | `prompt rm` |
| 6 | "The file is 32 MB and rewritten on every launch — bound it." (perf + hygiene) | `prompt prune`, eventual cap |
| 7 | "I keep retyping the same prompt; make it `#name` I can reuse." | `prompt save --as` (→ xprompt) |
| 8 | "I cancelled a prompt — what did it say?" (recovery, 723 cancelled today) | `list --cancelled` |
| 9 | "CLI, TUI, web, and editor should share one fast prompt store." (boundary rule) | move storage to `sase-core` |

## Recommended Solution

### 1. Read / inspect surface (Phase 1 — highest value, lowest risk)

Mirror `sase chats` exactly. Read-only; safe to ship independently of any storage change.

- **`sase prompt list [-j] [-l N] [-q SUBSTR] [--cancelled | --all]`** — recency-sorted (post-epic ordering). Rich table
  by default: `SELECTOR · LAST-USED · ✗? · preview`; `-j` emits a stable JSON array. Default hides cancelled (matches
  today's default); `--cancelled` shows only cancelled; `--all` shows both. `-l` defaults to a sane window (e.g. 20).
- **`sase prompt search QUERY [-j] [-l N]`** — thin sugar over `list -q` for discoverability (a *verb* is easier to find
  than a flag).
- **`sase prompt show SELECTOR [-j]`** — print the **full** prompt text to stdout (no truncation, no `$EDITOR`), so it
  composes: `sase run "$(sase prompt show a3f9)"`. `-j` adds metadata.
- **`sase prompt stats [-j]`** — atuin-style: total entries, file size, cancelled count + rate, oldest/newest, and the
  top referenced xprompts/workflows (parse `#name` tokens out of stored text). This is the feature that makes the perf
  problem *visible* and tells the user *what is worth promoting* (§3).

**Selectors:** address entries by a short **content hash** (e.g. first 4–7 chars of a SHA over `text`), printed in
`list`. A hash is stable as new prompts arrive (a positional index is not) and dedup is already by exact text, so a
content hash is a natural primary key. Accept a positional index too for convenience.

### 2. Maintenance surface (Phase 2 — fixes the measured problems)

- **`sase prompt prune [--before DATE] [--keep N] [--cancelled] [--dedup] [--dry-run]`** — the direct remedy for the
  32 MB / 9,064-entry file. `--keep N` retains the N most-recent; `--before` drops old; `--cancelled` drops only
  cancelled (would reclaim 723 today); `--dedup` collapses any residual exact dups; **`--dry-run` always reports what
  *would* be removed first.** Reuse the existing `flock` + atomic `os.replace` write path.
- **`sase prompt rm SELECTOR [-y]`** — delete a single entry. Primary use-case is **security scrubbing** (a prompt that
  inadvertently contains a secret/token) plus targeted cleanup.
- *(Optional)* **a soft cap** wired into `add_or_update_prompt()` (e.g. keep newest ~2–5k) so the file self-bounds even
  for users who never run `prune`. Mirrors `vcs_xprompt_mru.py`'s 100-cap pattern.

### 3. Curation bridge (Phase 3 — the ambitious, high-leverage piece)

- **`sase prompt save SELECTOR --as NAME [--project P] [--tag T...]`** — promote a history entry into a real **xprompt**:
  write `~/.xprompts/NAME.md` (or `~/.config/sase/xprompts/<project>/NAME.md` with `--project`) using the front-matter
  format the loader already understands (`src/sase/xprompt/loader_sources.py`), then it is instantly usable as `#NAME`.
  This closes the one genuine gap between the two prompt systems: today **nothing** turns "ran it 40 times" into a
  reusable, git-trackable template. `stats` surfaces the candidates; `save` performs the promotion. Because it writes
  plain `.md`, it is version-controllable — aligned with where the broader ecosystem (post-OpenAI-deprecation) is going.

### 4. Architectural track (ambitious, optional, separable)

Per `memory/short/rust_core_backend_boundary.md`, prompt history is **shared backend logic** — a web app, editor, or
another CLI would all need it to match the TUI — yet it lives only in Python today (confirmed: no `prompt_history` in
`sase-core/crates/sase_core`). A dedicated CLI is precisely the cross-frontend surface that rule anticipates.

Recommendation: when this work justifies it, move prompt-history **storage** into `sase-core` behind `sase_core_rs`,
backed by **SQLite** (atuin's choice for the same reason). Benefits: indexed `search`/`stats` without loading 32 MB,
appends instead of full rewrites on the launch hot path (resolves the `tui_perf` tension), and one store shared by every
frontend. **Practical interim:** ship Phases 1–3 on the current JSON file plus a cap/prune; the SQLite migration is a
follow-on that the CLI's stable `--json` contract makes safe to do later without breaking callers.

## Phasing

1. **Phase 1 — Read surface.** `list` / `search` / `show` / `stats`, `--json`, mirror `sase chats`. Read-only. Ship
   first; immediately useful and reversible.
2. **Phase 2 — Maintenance.** `prune` / `rm` (+ optional soft cap). Pay down the 32 MB / unbounded-growth debt.
3. **Phase 3 — Bridge.** `save --as` → xprompt. The differentiated, high-leverage feature.
4. **Phase 4 — (optional) Core/SQLite migration.** Move storage to `sase-core`; keep the CLI contract stable.

Sequence after / alongside epic **sase-4m** so the CLI is built on the recency-only model, not the
branch/workspace ranking being removed.

## Risks & Constraints

- **Don't add I/O to hot key handlers.** All `sase prompt` work runs in the CLI process, not Textual handlers — safe by
  construction, but keep it that way (`tui_perf`).
- **Preserve the write contract.** Any mutation (`rm`/`prune`/cap) must keep the sidecar `flock` + atomic
  `os.replace`/`fsync` behavior so concurrent agent launches never truncate the file.
- **Backward-compatible reads.** Honor legacy entries with `branch_or_workspace`/`workspace` fields (the epic keeps
  read-compat); don't require them.
- **Stable selectors.** Use content-hash IDs so a handle printed by `list` still resolves after new prompts land.
- **Destructive ops are guarded.** `prune`/`rm` default to confirmation / `--dry-run`; never delete silently.

## Out of Scope (with rationale)

- **Cross-machine sync + client-side encryption** (atuin has it). Valuable given SASE's remote-agent direction, but it
  is a large standalone subsystem; defer until after the local CLI proves the model.
- **A second TUI inside `sase prompt`.** The Textual modal already covers interactive browsing; the CLI's job is to be
  **scriptable-first** (pipes, `--json`, grep). Don't duplicate the modal.
- **Absorbing command history / MRU / chats.** Each has its own store and surface; `sase prompt` stays focused on prompt
  history, with the single deliberate bridge to xprompts.

## Sources

- atuin — shell history manager: <https://atuin.sh/>, <https://docs.atuin.sh/cli/>
- Prompt-management CLI: <https://github.com/prompt-management/cli>
- Best prompt libraries 2026: <https://pinggy.io/blog/best_prompt_libraries_for_ai_assisted_software_development/>
- OpenAI prompting / reusable-prompt deprecation: <https://developers.openai.com/api/docs/guides/prompting>
- In-repo: `sdd/epics/202606/prompt_history_tui.md`, `src/sase/history/prompt.py`,
  `src/sase/chats/cli_list.py`, `src/sase/main/query_handler/special_cases.py`,
  `src/sase/xprompt/loader_sources.py`, `memory/short/rust_core_backend_boundary.md`
</content>
</invoke>
