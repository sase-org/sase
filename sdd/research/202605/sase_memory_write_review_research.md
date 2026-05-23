# `sase memory write` / `sase memory review` Research

## Question

What is the best way to add two new `sase memory` subcommands?

- `sase memory write`: lets agents propose new long-term memory.
- `sase memory review`: lets users approve, reject, or approve with manual edits.

The command set should require one or more evidence items for every proposal, support non-interactive review actions,
and also provide a robust terminal review experience with a drill-down view.

## Current Local Architecture

The existing memory CLI is entirely in the Python `sase` repo. The new commands should reuse, not parallel, these
helpers:

- `src/sase/main/parser_memory.py` registers `sase memory {init,list,read,log}` with `argparse`; add `write` and
  `review` here as additional sub-subparsers.
- `src/sase/main/memory_handler.py` dispatches to small handler modules; the pattern is one new handler per command.
- `src/sase/memory/cli_read.py` is the closest precedent for an agent-attributable write-style command and is worth
  mirroring almost line-for-line for `cli_write.py`.
- `src/sase/memory/read_log.py` already owns the JSONL primitives the proposal store needs:
  - `discover_agent_identity(env)` and `require_agent_identity(env)` at lines 198 and 224 — reuse directly for `write`.
  - `_locked(path, mode)` context manager with `fcntl.LOCK_EX` / `fcntl.LOCK_SH` at lines 290 and 304 — copy this exact
    pattern, do not invent a new lock scheme.
  - 12-char hex IDs via `uuid4().hex[:12]` at line 259 — use the same length and alphabet for `proposal_id` so
    operational state stays uniform across `memory_reads.jsonl` and `memory_proposals.jsonl`.
- `src/sase/memory/inventory.py:build_memory_inventory()` (line 381) produces `MemoryEntryStatus` of
  `loaded | referenced | available | missing` (line 19). Approval flow must call this to detect when a newly approved
  file would only be `available` and warn the reviewer.
- `src/sase/xprompt/loader_memory.py` auto-discovers `memory/long/*.md` files with `keywords` frontmatter as dynamic
  memory xprompts; the approved file's frontmatter must match this loader's expected schema or the new memory will
  never load.

The docs already present `sase memory` as the right top-level group for memory inspection and audited reads
(`docs/init.md`, `docs/configuration.md`, `docs/cli.md`). The new commands fit naturally in that group.

## Adjacent Prior Research

These earlier notes establish constraints the new commands must respect:

- `sdd/research/202605/zettel_sase_shared_memory.md` is the load-bearing argument against direct agent writes and the
  source of the inbox/promotion-with-provenance pattern this design adopts.
- `sdd/research/202604/git_versioned_agent_memory.md` frames the broader project-scoped, runtime-agnostic memory
  problem; the proposal ledger sits in project-scoped operational state, not in the repo, exactly because that note
  argues canonical memory should be curated, not auto-mutated.
- `sdd/research/202604/short_term_vs_long_term_memory.md` quantifies the token cost of always-loaded short-term memory.
  Long-term memory is dynamic, but every approval still grows the dynamic-keyword pool. Review UI should surface line
  count and approximate token count for each proposal so reviewers can see the cost.
- `sdd/research/202604/dynamic_memory_critique.md` and `sdd/research/202604/dynamic_memory_implementation.md` describe
  how `keywords` matching gates loading. A proposed memory with no keywords becomes effectively unreachable except by
  explicit `@` reference; the review UI should flag this.
- `sdd/research/202604/agents_md_token_optimization.md` discusses keeping `AGENTS.md` / `memory/short` lean. Approval
  must never touch those files implicitly.
- `sdd/epics/202605/memory_command_1.md` defines the Rich dashboard for `sase memory list` — the pending-proposal count
  should appear there too, not only inside `review`.
- `sdd/epics/202605/memory_read_log.md` is the operational-state precedent the proposal ledger inherits from.
- `sdd/research/202604/notification_store_python_baseline.md` documents the notification append pattern that
  `sase memory write` should hook into so users see pending proposals in the existing inbox.

The combined constraint is firm: `write` creates a proposal, not a memory file, and the user is the only path to
`memory/long`.

## External/Library Notes

Textual is already a first-class dependency (`textual[syntax]>=0.45.0`, currently locked to `8.0.1` in `uv.lock`), so a
new terminal review surface should reuse Textual rather than introduce a second TUI framework.

Relevant official Textual docs:

- `DataTable` supports efficient row/cell display, cursor navigation, mouse clicks, and highlight/selection events:
  https://textual.textualize.io/widgets/data_table/
- `Markdown` displays Markdown documents and `MarkdownViewer` adds table-of-contents features:
  https://textual.textualize.io/widgets/markdown/
- `TextArea` supports multiline editing, soft wrap, and syntax highlighting through the installed `textual[syntax]`
  extra: https://textual.textualize.io/widgets/text_area/
- Textual apps are testable with `App.run_test()` and `Pilot.press` / `Pilot.click`; the docs also call out SVG snapshot
  testing as an option: https://textual.textualize.io/guide/testing/

Local TUI patterns are more important than generic docs. These are the most reusable references:

- `src/sase/ace/tui/modals/plan_approval_modal.py`: review Markdown, approve/reject/feedback/edit key actions, scroll
  controls.
- `src/sase/ace/tui/modals/mentor_review_modal.py`: two-pane review UI with side navigation, rich detail content,
  accepted state, and action keys.
- `src/sase/ace/tui/modals/approve_options_modal.py`: compact action chooser and explicit key-event barrier behavior.
- `tests/test_approve_options_modal_keys.py`, `tests/test_mentor_review_modal_actions.py`, and
  `tests/test_ace_tui_app.py`: practical examples for testing Textual interaction.

## Recommendation

Build this as a proposal/inbox workflow:

1. `sase memory write` validates agent identity and writes a pending proposal under project-scoped SASE state.
2. `sase memory review` lists pending proposals and applies review decisions.
3. Only an approval writes or updates `memory/long/*.md`.
4. Rejections remain in the proposal ledger for audit/history.
5. Manual edits happen before promotion, and the edited approved content becomes the canonical memory file.

Do not write proposals directly into `memory/long`. That would make untrusted or mistaken agent output available to
future agents before human review and would conflict with the security guidance in the existing zettel/shared-memory
research.

## Proposed Command Contract

### `sase memory write`

Recommended initial shape:

```bash
sase memory write \
  --title "Generated skill files are rendered from xprompts" \
  --slug generated-skills \
  --keywords "SKILL.md,init-skills,commit skill" \
  --evidence "memory/long/generated_skills.md" \
  --evidence "src/sase/xprompts/skills/sase_git_commit.md" \
  --body-file /tmp/memory.md
```

Flags:

| Flag | Recommendation |
| --- | --- |
| `--title` | Required, short human label. Used in review UI and as fallback heading. |
| `--slug` | Optional. If absent, derive from title. Validate to `[a-z0-9][a-z0-9_-]*`; target file is `memory/long/<slug>.md`. |
| `--keywords` | Optional comma-separated list. If present, becomes YAML `keywords` frontmatter on approval. |
| `--evidence` | Required, repeatable. Every proposal must have at least one. Store exactly, plus parsed hints when possible. |
| `--body` | Optional inline body for short proposals. |
| `--body-file` | Optional file input for normal proposals. Use `-` for stdin. |
| `--target` | Optional exact `long/foo.md` target. Mutually exclusive with `--slug`; useful for proposing updates to an existing memory. |
| `--json` | Optional machine-readable output containing proposal id, status, and state path. |

`--body` and `--body-file` should be mutually exclusive, with one required.

Evidence should start simple and auditable. Treat it as a repeated string option in the CLI, but normalize each item into
a structured record:

```json
{
  "raw": "src/sase/memory/read_log.py:48",
  "kind": "path",
  "path": "src/sase/memory/read_log.py",
  "line": 48,
  "note": null
}
```

Known patterns worth recognizing:

- repo-relative file path, optional `:line`;
- absolute path inside the current workspace;
- URL;
- free-form text.

Avoid fetching URLs or embedding large evidence content in the first version. The proposal should preserve references,
not copy the world into state.

### `sase memory review`

Recommended non-interactive forms:

```bash
sase memory review --list --json
sase memory review --show <proposal-id>
sase memory review --approve <proposal-id>
sase memory review --approve <proposal-id> --target long/foo.md
sase memory review --reject <proposal-id> --reason "Too speculative"
sase memory review --edit <proposal-id>
```

Flags:

| Flag | Recommendation |
| --- | --- |
| `--list` | Print pending proposals with Rich by default, JSON with `--json`. |
| `--show ID` | Static detail view for scripts or simple terminals. |
| `--approve ID` | Non-interactive approval. Writes/updates `memory/long/*.md`, marks proposal approved. |
| `--reject ID` | Non-interactive rejection. Requires `--reason` unless `--yes` is added intentionally later. |
| `--edit ID` | Open `$VISUAL` / `$EDITOR` for manual edits, then approve the edited content after confirmation. |
| `--target long/foo.md` | Override target path during approval. Validate under `memory/long`. |
| `--json` | Deterministic output for automation. |
| no action flags | Launch the Textual review app when stdout is a TTY; otherwise print pending list and exit nonzero with guidance. |

Do not overload `--approve --edit` in the first pass unless needed. A clearer first version is `--edit ID`, which means
"edit and approve if the editor exits successfully and validation passes." Interactive UI can expose the same operation
as the `e` key.

## Storage Design

Use project-scoped operational state under `~/.sase/projects/<project>/`, matching `memory_reads.jsonl`.

Recommended files:

```text
~/.sase/projects/<project>/memory_proposals.jsonl
~/.sase/projects/<project>/memory_proposals.lock
```

Append-only JSONL is the right starting point because:

- `memory_read_log.py` already uses JSONL plus `fcntl` locks in Python.
- the Rust core notification store uses JSONL plus lock files (`sase-core/crates/sase_core/src/notifications/store.rs`),
  which confirms the cross-repo pattern.
- pending/rejected/approved proposal history is audit data, not canonical memory source.

Rows should be event-like, not mutable snapshots. Keep the implementation simple by reading all rows and reducing them
to current proposal states.

Suggested schema:

```json
{
  "schema_version": 1,
  "event_id": "b9c7d2a1044e",
  "proposal_id": "mem-20260523-153012-a1b2",
  "event_type": "proposed",
  "timestamp": "2026-05-23T15:30:12Z",
  "project": "sase",
  "cwd": "/home/bryan/projects/github/sase-org/sase_23",
  "agent_name": "agent-name",
  "agent_source": "SASE_AGENT_NAME",
  "artifacts_dir": "...",
  "target_path": "long/generated_skills.md",
  "title": "Generated skill files are rendered from xprompts",
  "keywords": ["SKILL.md", "init-skills", "commit skill"],
  "body": "# Generated Skill Files\n...",
  "evidence": [
    {"raw": "memory/long/generated_skills.md", "kind": "path", "path": "memory/long/generated_skills.md"}
  ]
}
```

Review events:

- `approved`: reviewer, target path, final content hash, final byte count.
- `approved_with_edits`: same as approved, plus `edited: true`; do not need to store both pre/post body if the original
  proposal event is in the ledger.
- `rejected`: reviewer and reason.

Agent identity should reuse `discover_agent_identity()` / `require_agent_identity()` from
`src/sase/memory/read_log.py:198,224`. There is no existing reviewer-identity precedent in the read log
(reads are agent-only), so the new commands need a small new helper:

- New `reviewer_identity()` returning `{user, host, source}` where `source` is `SASE_USER` if set, else
  `getpass.getuser()` and `socket.gethostname()`.
- Tests should fix both via env / monkeypatch the same way `test_memory_read_log.py` fixes agent identity.
- Do not require reviewer identity at all when running fully non-interactively in CI-style automation; tag the event
  `source: "auto"` so the ledger distinguishes human approvals from scripted ones.

## Canonical Memory Write Behavior

Approval should validate and write only under `memory/long`.

Recommended target handling:

- Accept `long/foo.md` or derive from `--slug` / title.
- Reject absolute paths, traversal, non-`.md`, and `short/...` targets.
- If target exists, treat the proposal as an update and show a diff in review.
- If target does not exist, create it.
- Use atomic write (`tempfile` in same directory + `os.replace`) to avoid partial files.

Approved file format:

```markdown
---
keywords: [foo, bar]
---

# Title

Body...
```

Do not embed the full evidence list in the approved memory body by default. Evidence belongs in the proposal ledger. If
reviewers want visible provenance, add a short footer later, but keep the first canonical memory files clean and useful
as agent context.

After approval, call `src/sase/memory/inventory.py:build_memory_inventory()` and inspect the new file's
`MemoryEntryStatus`:

- `loaded` — covered.
- `referenced` — covered, but warn if the only reference is from another `long/` file (still requires keyword hit to
  actually load).
- `available` — warn loudly: the file exists but is unreachable unless an agent prompt happens to match a keyword.
  Suggest adding keywords or an `@` reference from `memory/short` or `AGENTS.md`.
- `missing` — bug; abort approval.

Do not auto-edit `AGENTS.md` or `memory/short` without explicit user approval, even when status is `available`. The
warning is the right escape valve, not a silent edit.

Also surface file metrics in the review UI before approval: byte count, line count, and an approximate token count
(use the same heuristic the inventory's `loaded_token_count` uses at `inventory.py:443`). This makes the cost discussed
in `sdd/research/202604/short_term_vs_long_term_memory.md` visible at the point of decision.

## Notification Integration

`sase memory write` should emit a SASE notification so users see pending proposals in the existing inbox without
polling `sase memory review --list`. The notification store is already plumbed end-to-end:

- `src/sase/notifications/store.py:append_notification()` is the append entry point (backed by the Rust core notification
  store).
- `src/sase/notifications/senders.py` contains seven precedent senders; add an eighth, e.g.
  `send_memory_proposal_notification(proposal_id, title, agent)`.
- The notification's `action` field should be `"memory_review"` and `action_data` should carry `{"proposal_id": "..."}`
  so a future ACE / mobile / Telegram surface can deep-link into the review flow without depending on the Python CLI
  layout.
- Use `notes` for the human-readable summary (title, agent name, evidence count) and `files` for the resolved evidence
  paths so the existing notification modal already knows how to render them.

Approval and rejection should mark that notification as read / dismissed, not create new ones, to avoid inbox spam when
a reviewer churns through several proposals in one session.

## Concurrency and Deduplication

The proposal ledger is append-only and locked, but the higher-level workflow needs a few rules:

- Two agents may propose the same `--slug` simultaneously. The reducer should treat them as separate proposals
  (different `proposal_id`) and let the reviewer pick one or merge. Do not collapse them silently.
- Before appending a new proposal event, compute a content hash (sha256 of normalized body + target). If the same hash
  is already in `pending` state, `write` should refuse with a clear message and emit the existing `proposal_id`. Use
  `--force` to bypass.
- A proposal targeting an existing `memory/long/foo.md` should record the current file's content hash at proposal time.
  At approval time, recompute the hash and warn if the on-disk file changed between proposal and approval — the
  reviewer should see the divergence diff before promoting.
- `review --approve` should refuse if the proposal's status is anything other than `pending` (already approved, already
  rejected, superseded). Re-approving is a new proposal, not a state toggle.

These rules are cheap to implement on top of the JSONL reducer and prevent the most common foot-guns.

## JSON Output Contract

`--json` is currently informal across `sase memory` subcommands. Because the new commands are the first ones agents are
expected to drive non-interactively, define the schema now and document it in `docs/cli.md`:

```json
// sase memory write --json
{
  "ok": true,
  "proposal_id": "a1b2c3d4e5f6",
  "status": "pending",
  "target": "long/generated_skills.md",
  "state_path": "/home/<user>/.sase/projects/sase/memory_proposals.jsonl",
  "notification_id": "n_..."
}

// sase memory review --list --json
{
  "schema_version": 1,
  "project": "sase",
  "proposals": [
    {
      "proposal_id": "a1b2c3d4e5f6",
      "status": "pending",
      "title": "...",
      "target": "long/...md",
      "agent": "agent-name",
      "evidence_count": 2,
      "created": "2026-05-23T15:30:12Z"
    }
  ]
}

// sase memory review --approve <id> --json
{
  "ok": true,
  "proposal_id": "a1b2c3d4e5f6",
  "status": "approved",
  "target_path": "memory/long/generated_skills.md",
  "bytes_written": 1832,
  "warnings": ["inventory_status: available"]
}
```

Exit codes:

- `0` — success.
- `2` — argparse usage error (default).
- `3` — proposal not found.
- `4` — proposal in wrong state (e.g., approving an already-approved id).
- `5` — validation failure (bad target path, missing evidence, hash drift).
- `6` — write failed (filesystem, lock contention beyond retry budget).

Reserve `1` for unexpected exceptions to match standard CLI conventions.

## Textual Review Experience

Build a standalone app, not an ACE modal. `sase memory review` is a CLI workflow and should not require launching
`sase ace`.

Recommended layout:

```text
+ SASE Memory Review ------------------------------------------------------+
| pending: 4   approved: 12   rejected: 3   project: sase                  |
+------------------------------+-------------------------------------------+
| Proposals                    | Detail                                    |
| > mem-... generated skills   | title / target / agent / age / evidence   |
|   mem-... tui perf gotcha    |                                           |
|   mem-... telegram setup     | Markdown preview or diff                  |
+------------------------------+-------------------------------------------+
| j/k navigate  enter drill down  a approve  e edit+approve  r reject  q quit |
+--------------------------------------------------------------------------+
```

Drill-down view should be a second screen or mode for the selected proposal:

- full Markdown preview;
- metadata panel;
- evidence list;
- existing-target diff when updating an existing memory;
- actions: approve, edit+approve, reject, copy id/path, back.

Implementation choices:

- Use `DataTable` or `OptionList` for the left proposal list. `DataTable` is better if filters/sort columns land soon;
  `OptionList` is simpler and matches several existing SASE modals.
- Use `Markdown`/`MarkdownViewer` for proposal body preview.
- Use Rich `Syntax` with `markdown`/`diff` lexer for body and target diff when consistency with existing modals matters.
- Use Textual `TextArea` only if in-app editing is required. For the first robust implementation, shelling out to
  `$VISUAL`/`$EDITOR` is safer for serious edits; the TUI can suspend, open the editor, reload the edited temp file,
  validate, and then approve.

The local `MentorReviewModal` pattern is the best model: a compact side panel, rich main panel, explicit navigation
keys, and separate state builders. Avoid burying proposal logic in widget methods. Use:

- `src/sase/memory/proposals.py`: model, validation, append/read/reduce helpers.
- `src/sase/memory/cli_write.py`: thin command handler.
- `src/sase/memory/cli_review.py`: non-interactive command handler and TTY dispatch.
- `src/sase/memory/review_tui.py`: standalone Textual app/screens.

## Core Boundary Decision

The short-term implementation can stay in Python because:

- existing memory CLI, inventory, dynamic memory, and read audit code are Python;
- `review` is a CLI/TUI surface, and no sibling frontend currently consumes memory proposals;
- this keeps the first patch small and avoids forcing a Rust/PyO3 binding for a still-evolving workflow.

However, design the proposal model as if it could move to `sase-core` later:

- schema-version every event;
- keep validation pure and covered by tests;
- avoid Textual/Rich imports in storage/model code;
- keep JSON payloads deterministic.

If Telegram, mobile, web, or nvim need to list/approve proposals, promote the storage/reducer/validation layer to
`sase-core` and leave Python as a frontend adapter. This matches the repo's Rust core boundary guidance.

Reality check on the sibling repos today (verified May 2026):

- `sase-telegram_23` has no memory surfaces and only consumes notifications. The `action="memory_review"` notification
  payload is sufficient for a future Telegram approve-button feature without any core promotion.
- `sase-nvim_23` does not consume the memory inventory or the notification store. Nothing to update there for v1.
- `sase-core_23` already hosts the notification store JSONL+lock pattern at
  `crates/sase_core/src/notifications/store.rs`, which is the structural model the proposal store should imitate so a
  future port is cheap.

## Security and Quality Constraints

The biggest risk is memory poisoning. Guardrails for the first version:

- Require agent attribution, reusing the `sase memory read` identity rules.
- Require at least one `--evidence`.
- Keep proposals pending until reviewed by a user.
- Store proposal history outside the repo in project SASE state.
- Validate target paths under `memory/long`.
- Reject empty bodies and very large bodies by default; add `--allow-large` only if necessary.
- Display evidence prominently in review before the action keys.
- Require an explicit rejection reason for non-interactive rejection.
- Never edit `memory/short` or instruction files as a side effect.

Consider a warning when a proposal contains instruction-like text such as "ignore previous instructions", "always trust",
or attempts to redefine agent policy. This can be heuristic in v1; the human review step is the real defense.

## Testing Plan

Model/storage tests:

- `write` requires attribution and evidence.
- target path validation rejects traversal, absolute paths, `short/...`, and non-markdown files.
- proposal JSONL append/read tolerates malformed rows like `memory_read_log.py`.
- reducer returns the latest state and hides approved/rejected proposals from the pending list by default.
- approval writes the expected `memory/long/*.md` frontmatter/body and appends an approval event.
- rejection appends a rejection event and does not write memory.

CLI tests:

- parser accepts repeated `--evidence`.
- `sase memory write ... --json` emits proposal id and state path.
- `sase memory review --list --json` is deterministic.
- `--approve`, `--reject`, and `--show` work without a TTY.
- non-TTY bare `review` does not try to launch Textual.

TUI tests — model these on the existing modal tests rather than starting from the Textual docs:

- `tests/test_mentor_review_modal_actions.py` — best precedent for two-pane review actions with state assertions.
- `tests/test_plan_approval_modal_title.py` — header and content-pane rendering plus key handling.
- `tests/test_approve_options_modal_keys.py` — compact action chooser key dispatch.
- `tests/test_notification_modal_actions.py` — relevant if the review TUI is reached via the notification flow.
- `tests/test_ace_tui_app.py` — Pilot harness setup for full-app launches.

The test points to hit:

- launch with `App.run_test()`;
- `j/k` moves selection;
- `enter` opens drill-down and `escape` returns;
- `a` triggers approval callback;
- `r` opens rejection flow or marks rejected with supplied reason in test harness;
- `e` suspends, runs a fake editor (env-injected), and applies edited body;
- render at 80x24 and a wider size to catch layout regressions.

Visual snapshot testing is optional for v1, but the repo already has Textual Pilot tests and PNG/SVG snapshot experience
that can be copied if the UI becomes central — see `tests/ace/tui/visual/` for the existing harness.

## Phased Implementation

### Phase 1: Proposal Store and `write`

- Add `src/sase/memory/proposals.py`.
- Add `src/sase/memory/cli_write.py`.
- Extend parser and handler.
- Store pending proposals in project-scoped JSONL.
- Require repeated `--evidence` with minimum one item.

### Phase 2: Non-Interactive `review`

- Add list/show/approve/reject command modes.
- Validate and atomically write approved `memory/long` files.
- Append review events.
- Add JSON output for automation.

### Phase 3: Textual Review App

- Add standalone `review_tui.py`.
- Implement list/detail layout.
- Add drill-down screen.
- Wire approve, reject, edit+approve actions.

### Phase 4: Polish and Docs

- Update `docs/init.md`, `docs/configuration.md`, and `docs/cli.md`.
- Add examples to parser epilog.
- Add focused Textual tests.
- Run `just install` and `just check` for source changes.

## Open Decisions

- Whether `--keywords` should be required. I recommend optional: some long-term memories are manually referenced rather
  than dynamic, and review can add keywords. The TUI should still flag a keyword-less proposal as low-reachability per
  `dynamic_memory_critique.md`.
- Whether approved files should include provenance comments. I recommend no for v1; keep provenance in the ledger.
- Whether in-app editing should use Textual `TextArea` immediately. I recommend `$EDITOR` first for robust real editing,
  then consider `TextArea` if users want a fully contained review flow.
- Whether approval should auto-stage/commit memory files. I recommend no for v1; keep the command focused on memory
  review and leave VCS to the normal SASE commit workflow.
- Whether `sase memory list` should display pending-proposal counts. I recommend yes; it is a single reducer call and
  keeps the user from having to remember the new `review` command exists.
- Whether to support `--supersede <id>` on `write` for an agent that wants to replace a still-pending proposal it
  authored. Recommend deferring; v1 reviewers can reject the old proposal manually.
- Whether to rate-limit per-agent proposals. Recommend deferring with a TODO; the notification inbox will make any
  runaway agent visible quickly enough for v1.

## Bottom Line

Implement `write` as an attributable proposal inbox and `review` as the promotion gate. Use the current Python memory
CLI and JSONL operational-state pattern for the first version. Use a standalone Textual review app modeled on the local
mentor/plan review modals for the beautiful interactive path, while keeping every action scriptable through
non-interactive CLI flags.
