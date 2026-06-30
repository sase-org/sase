---
create_time: 2026-06-30 09:45:28
status: done
prompt: sdd/prompts/202606/bead_list_limit_and_implicit_closed.md
---
# Plan: `sase bead list` — `--limit` option and implicit `--status closed` fallback

## Goal

Improve the ergonomics of `sase bead list` with two related changes:

1. **`-n | --limit <N>`** — cap how many beads the command prints.
2. **Implicit `--status closed` fallback** — when the user does _not_ pass `--status` and the default (open +
   in‑progress) view is empty, fall back to showing closed beads, and print a short notice telling the user we implied
   `--status closed`.

Both are CLI/presentation-level conveniences layered on top of the existing Rust-backed bead read path.

## Background / current behavior

- `sase bead list` is handled by `handle_bead_list` in `src/sase/bead/cli_query.py`. With no `--status`, it lists
  `open` + `in_progress` beads; otherwise it honors the repeatable `--status` filters. It also supports repeatable
  `--type` and `--tier` filters. Empty result prints `No issues found.`
- The argument parser lives in `src/sase/main/parser_bead.py` (`register_bead_parser`). The `list` subparser currently
  has `--status`, `--type`, `--tier` (no `--limit`).
- The sibling `sase bead search` command **already** has a `-n | --limit` option using the shared `nonnegative_int` arg
  type (`default=None`, documented as "0 means unlimited"). Its limit is pushed down into the Rust core (`bead_search` →
  `search_issues`) because search's limit interacts with match ranking ("keep the newest matches").
- Reads flow Python → `BeadProject.list_issues` (`src/sase/bead/project.py`) → `bead_read_facade.list_issues`
  (`src/sase/core/bead_read_facade.py`) → Rust `bead_list` binding → `sase_core` `list_issues` /
  `list_issues_in_issues`. The Rust path returns beads **sorted ascending by `created_at`** (oldest first).
- Per repo conventions: bare `sase bead` already delegates to `sase bead list` via the central
  `_default_list_subcommands()` wiring, so both new behaviors automatically apply to the bare invocation too (no extra
  work, but worth verifying).

## Design decisions (please confirm at review)

1. **Where `--limit` is applied — Python, not Rust.** For `search`, the limit lives in Rust because it is entangled with
   relevance ranking. For `list` there is **no ranking** — the Rust layer already returns a fully sorted list and the
   limit is pure display truncation. We will apply it in Python in `handle_bead_list`. This keeps the change in one
   repo, honors the Rust-core boundary ("presentation / Python glue stays here"; no domain logic is reimplemented — we
   reuse the Rust-sorted result and slice it), and avoids a `list_issues` signature change that would ripple through
   every Rust caller (gateway routes, `bead/cli.rs`, the xprompt LSP server, parity tests) plus the PyO3 binding and two
   repos' tests.
   - _Alternative considered:_ push `limit` into `sase_core` `list_issues` / `list_issues_in_issues` + the `bead_list`
     PyO3 binding, mirroring search exactly. Rejected as disproportionate for a no-ranking truncation, but easy to
     switch to if you prefer strict parity with `search`.

2. **Which N the limit keeps — the newest N.** The Rust list is oldest→newest. `--limit N` will keep the **newest N**
   beads (the tail of the sorted list) and still display them in the existing oldest‑first order, i.e. `issues[-N:]`.
   This matches `search`'s "keep the newest matches" intent and the common expectation (cf. `git log -n`). The unlimited
   path (`--limit 0` or omitted) is byte-for-byte unchanged.
   - _Alternative:_ keep the oldest N (`issues[:N]`). Easy to flip if preferred.

3. **`--limit` semantics mirror `search`.** Reuse `nonnegative_int`, `default=None`; `0` means unlimited; negatives are
   rejected by argparse. Short alias `-n`, long `--limit`, same help phrasing.

4. **What "no open beads to show" means — the default view is empty.** The fallback triggers when the _default_ listing
   (open + in_progress) under the currently-active `--type` / `--tier` filters returns zero beads. This preserves
   today's behavior whenever anything is showable and only changes the empty case. (If you'd rather key strictly on
   `status == open` and ignore in_progress, that's a one-line change — flagged because the prompt said "open beads"
   while the current default also includes in_progress.)

5. **Fallback only when `--status` is omitted.** If the user explicitly passes any `--status` (including
   `--status open`), we never auto-fall-back and never print the notice — explicit intent wins.

6. **Notice is informational, printed to stdout** before the rows, consistent with the existing `No issues found.`
   message. Proposed wording (final wording open to your preference):
   `No open beads to show — defaulting to --status closed.`

## Behavior matrix

| Invocation                            | Open/in‑progress exist? | Closed exist?       | Result                                               |
| ------------------------------------- | ----------------------- | ------------------- | ---------------------------------------------------- |
| `sase bead list`                      | yes                     | —                   | list open+in_progress (unchanged)                    |
| `sase bead list`                      | no                      | yes                 | notice + list closed beads                           |
| `sase bead list`                      | no                      | no                  | `No issues found.` (no notice)                       |
| `sase bead list --status open`        | no                      | yes                 | `No issues found.` (explicit; no fallback)           |
| `sase bead list --type phase`         | no phases open          | closed phases exist | notice + closed phases (filters carry into fallback) |
| `sase bead list -n 5`                 | >5 open                 | —                   | newest 5 open beads                                  |
| `sase bead list -n 0`                 | any                     | —                   | unlimited (same as omitting)                         |
| `sase bead list -n 3` (fallback case) | no                      | >3 closed           | notice + newest 3 closed beads                       |

Ordering of concerns in the handler: resolve filters → run default query → (if empty and no explicit `--status`) run
closed query and set the implicit flag → if still empty print `No issues found.` and return → print notice if implicit →
apply `--limit` to whichever set we're showing → print rows. (Limit never affects the emptiness decision: capping a
non-empty set keeps it non-empty, and `0`/`None` = unlimited.)

## Implementation outline

### 1. Parser — `src/sase/main/parser_bead.py`

Add a `-n | --limit` argument to `bead_list_parser`, mirroring the existing `search` definition (`type=nonnegative_int`,
`default=None`, help: "Maximum beads to print; 0 means unlimited"). Keep options ordered/scannable per the CLI rules
(`--limit` is already alphabetically before `--status`/`--type`/`--tier`).

### 2. Handler — `src/sase/bead/cli_query.py` (`handle_bead_list`)

- Track whether `--status` was explicitly provided.
- Default statuses = `[OPEN, IN_PROGRESS]`; run `view.list_issues(...)` with the active type/tier filters.
- If result empty **and** no explicit status: re-query with `statuses=[CLOSED]` (same type/tier filters). If that's
  non-empty, adopt it and set an `implicit_closed` flag.
- If still empty → `No issues found.` and return.
- If `implicit_closed` → print the notice.
- Apply limit: `issues = issues[-limit:] if limit else issues` (limit truthy ⇒ non-zero).
- Print rows unchanged (`{icon} {id} · {title}{ ← parent}`).

No change to `BeadProject` / facade / Rust under the chosen design.

### 3. Tests — `tests/test_bead/`

- **Parser** (alongside the existing search parser tests): `list` accepts `-n/--limit`, stores int; `--limit 0` → `0`;
  negative rejected (SystemExit).
- **Handler / golden** (`test_cli_golden.py` uses fixtures + `*.stdout` goldens):
  - Default unchanged on the `current` fixture (existing `list.stdout` stays valid).
  - `--limit` keeps newest N (and `-n 0` = unlimited).
  - Implicit fallback: fixture with only closed beads → notice + closed rows.
  - Explicit `--status open` on that fixture → `No issues found.`, no notice.
  - Both-empty fixture → `No issues found.`, no notice.
  - Fallback respects `--type` / `--tier` filters. Add new golden `.stdout` files / fixtures as needed.

### 4. Docs / skill source — `src/sase/xprompts/skills/sase_beads.md`

- Update the `### list` section: add `--limit` examples and a one-line note on the implicit `--status closed` fallback +
  notice.
- If a list-example contract test is added (paralleling `test_search_skill_examples_parse_against_cli_contract` in
  `tests/test_bead/test_cli_search.py`), keep examples in sync with it.
- Regenerate + deploy the skill per the generated-skills workflow: `sase skill init --force` then `chezmoi apply` (do
  not hand-edit the deployed `SKILL.md`).

## Validation

- `just install` (ephemeral workspace may have stale deps) then `just check` (ruff + mypy + tests).
- Manual smoke: `sase bead list`, `sase bead list -n 1`, `sase bead list -n 0`, and a closed-only store to see the
  implicit notice + bare `sase bead` delegation.

## Out of scope

- Pushing the limit into the Rust core (documented alternative above).
- Colorizing `list` output (CLI-rules nicety, separate change).
- Pagination/offset or `--limit` for other bead subcommands.

## Open questions for the reviewer

1. Approve applying `--limit` in Python vs. Rust-core parity with `search`?
2. Keep **newest** N (recommended) or oldest N?
3. Fallback trigger = "default (open+in_progress) view empty" (recommended) or strictly "no `open` beads"?
4. Final wording of the implicit-`--status closed` notice.
