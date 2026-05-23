---
create_time: 2026-05-23
status: research
---

# `sase memory write` and `sase memory review`

## Question

How should SASE implement two new `sase memory` commands so agents can propose new long-term memories with evidence,
and users can review, reject, approve, or approve with edits from both non-interactive CLI flags and a high-quality
terminal review UI?

## Recommendation

Implement `sase memory write` as an **agent proposal capture** command, not a direct writer to `memory/long/*.md`.
Implement `sase memory review` as the only command that can promote a proposal into canonical long-term memory.

Recommended v1 command surface:

```bash
sase memory write --title TITLE --evidence EVIDENCE [--evidence EVIDENCE ...] \
  [--target long/topic.md] [--slug SLUG] [--keyword KW ...] \
  [--from-chat CHAT_ID] [--file draft.md | --body TEXT | -] [--json]

sase memory review                                  # interactive Textual app on a TTY
sase memory review --list [--json] [--all]          # non-interactive listing
sase memory review PROPOSAL_ID --show [--json]      # static detail view
sase memory review PROPOSAL_ID --approve [--target long/topic.md] [--edited-file edited.md]
sase memory review PROPOSAL_ID --edit               # opens $EDITOR, validates, then approves
sase memory review PROPOSAL_ID --reject --reason "Not durable or not supported"
```

Product rule: `write` creates a reviewable proposal under SASE state. It never modifies `memory/short/` or
`memory/long/`. `review --approve` (or its `--edit` equivalent) is the first point where canonical repo files change.

## Current Local State

The current `sase memory` command group already exists:

- `src/sase/main/parser_memory.py` registers `init`, `list`, `read`, and `log`.
- `src/sase/main/memory_handler.py` dispatches those subcommands.
- `src/sase/memory/cli_list.py` renders a Rich memory dashboard.
- `src/sase/memory/cli_read.py` reads only `memory/long/*.md`, strips leading YAML frontmatter, and appends an
  attributable audit log event.
- `src/sase/memory/read_log.py` stores read events as JSONL under `~/.sase/projects/<project>/memory_reads.jsonl`
  with `fcntl.flock` locking, atomic frontmatter handling, and an `AgentIdentity` discovery helper.
- `src/sase/memory/inventory.py` understands loaded, referenced, available, and missing memory files across project
  and home context roots, and exposes `build_memory_inventory()`.

That gives three strong implementation precedents:

1. Agent-initiated memory operations should be attributable — `read` already requires
   `SASE_AGENT_NAME`, `SASE_AGENT`, or `SASE_ARTIFACTS_DIR/agent_meta.json`.
2. Project-scoped memory audit state already lives under `~/.sase/projects/<project>/`, not inside the ephemeral
   workspace clone.
3. JSONL plus `fcntl` is the established storage shape for memory operational state.

Dynamic long-term memory discovery is still file-based and brittle in two important ways:

- `src/sase/xprompt/loader_memory.py` auto-discovers top-level `memory/long/*.md` files **only when** they have a
  YAML `keywords` list. Files with no `keywords` are silently invisible to dynamic memory.
- It uses `glob("*.md")`, not recursive discovery. v1 approvals must target `long/<slug>.md` (one level), not nested
  paths.

The sibling Rust core has xprompt catalog support for memory entries, but no memory proposal/review API. Per
`memory/short/rust_core_backend_boundary.md`, the proposal data model should be designed as a stable wire shape so it
can move to `sase-core` later, even if the first CLI implementation is Python-only.

A companion file in this same directory, `sase_memory_command_subcommands.md`, designed the broader v2 propose/review
surface and recommends inbox-first agent writes with provenance. Treat this note as the deeper drill-down on the
`write`/`review` slice of that plan.

## Why State Should Not Live in the Workspace

Earlier memory research left open whether proposals should live in `.sase/memory/inbox/` or project-local state. For
the `write` command specifically, the right answer is `~/.sase/projects/<project>/memory_proposals*`.

Reasons:

- SASE agents run in numbered, ephemeral workspace clones (`sase_<N>`). A proposal written to `.sase/memory/inbox/`
  inside an agent clone can be invisible from the user's normal review workspace and lost when the clone is reaped.
- The existing read audit log already lives at `~/.sase/projects/<project>/memory_reads.jsonl`. Co-locating
  proposal state there keeps memory operational state in one place.
- Proposal files are not canonical memory and must not dirty the user's repo before review.
- A project-scoped state path lets multiple agents propose concurrently and lets a user review from any workspace
  for that project.

## Storage Architecture: Ledger + Per-Proposal Body

Two storage shapes were considered. Both have precedent in this repo:

| Option                       | Precedent                                                                       | Strengths                                                                       | Weaknesses                                                                          |
| ---------------------------- | ------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| **JSONL event ledger**       | `memory_reads.jsonl`, `sase-core` notifications store, ChangeSpec hook history. | Append-only, tolerant of malformed rows, easy to replay, single lock.           | Bodies must be embedded or referenced; large bodies bloat the ledger.               |
| **Per-proposal JSON+body**   | `sase chats` artifact directories, agent artifacts dirs.                        | Bodies live as real files (editor-friendly), per-id isolation, simple browsing. | Two mutable files per proposal; concurrent state transitions need careful locking.  |

**Recommendation: a hybrid.** Use a JSONL event ledger for proposal *events*, and a per-proposal subdirectory for the
*draft / edited body*. Current proposal state is the reduction of all events for a given `proposal_id`.

```text
~/.sase/projects/<project>/
  memory_reads.jsonl              # existing
  memory_proposals.jsonl          # new: append-only event ledger
  memory_proposals.lock           # new: fcntl lock companion (matches read_log)
  memory_proposals/               # new: per-proposal working directories
    mem-20260523-142233-a1b2c3d4/
      draft.md                    # original agent-provided body
      reviewed.md                 # present only after --edit / --edited-file
      evidence_cache.json         # optional: cached hashes/excerpts, regenerable
```

This hybrid:

- Reuses the exact lock/append/replay code already proven in `read_log.py` (`_locked`, `append_memory_read_event`,
  `read_memory_read_events`).
- Keeps bodies as real `.md` files so `$EDITOR` and Textual `Markdown` widgets work without temp-file plumbing.
- Lets the reducer derive current state (`pending`, `approved`, `rejected`, `approved_with_edits`) without locking
  a mutable JSON file.
- Is easy to migrate into `sase-core` later: the JSONL row schema is the wire contract; the body directory is an
  implementation detail of the Python frontend that the core API can adopt or replace.

### Event Schema (v1)

Every row is one event. Mirror `MemoryReadEvent` in `read_log.py` (frozen dataclass, `schema_version`, sort-keys
JSON).

```json
{
  "schema_version": 1,
  "event_id": "b9c7d2a1044e",
  "proposal_id": "mem-20260523-142233-a1b2c3d4",
  "event_type": "proposed",
  "timestamp": "2026-05-23T18:22:33+00:00",
  "project": "sase",
  "cwd": "/home/bryan/.local/state/sase/workspaces/sase-org/sase/sase_10",
  "agent_name": "agent.foo",
  "agent_source": "SASE_AGENT_NAME",
  "artifacts_dir": "/home/bryan/.sase/projects/sase/artifacts/...",
  "title": "TUI modal pilot tests use Textual run_test",
  "slug": "tui_modal_testing",
  "target_path": "long/tui_modal_testing.md",
  "keywords": ["Textual modal", "run_test", "pilot test"],
  "body_path": "memory_proposals/mem-.../draft.md",
  "body_sha256": "sha256:...",
  "byte_count": 1234,
  "from_chat": null,
  "evidence": [
    {
      "raw": "tests/ace/tui/test_agent_tag_modal_pilot.py:42",
      "kind": "path",
      "path": "tests/ace/tui/test_agent_tag_modal_pilot.py",
      "line": 42,
      "resolved_path": "/abs/path/...",
      "sha256": "sha256:...",
      "byte_count": 1234,
      "exists_at_proposal_time": true
    },
    {"raw": "https://example.com/spec", "kind": "url", "url": "https://example.com/spec"},
    {"raw": "chat:abc12345", "kind": "chat", "chat_id": "abc12345"}
  ]
}
```

Review events share `proposal_id` but use different `event_type`s and a reviewer identity block:

```json
{
  "event_type": "approved",
  "reviewer_user": "bryan",
  "reviewer_host": "obsidian",
  "reviewer_source": "getpass",
  "target_path": "memory/long/tui_modal_testing.md",
  "approved_body_path": "memory_proposals/mem-.../draft.md",
  "approved_body_sha256": "sha256:...",
  "edited": false
}
```

Event types:

- `proposed` — initial creation. Required fields above.
- `approved` — promotion succeeded; `edited: false`.
- `approved_with_edits` — promotion succeeded from `reviewed.md`; `edited: true`.
- `rejected` — requires non-empty `reason`.
- `retracted` (later) — paired with `sase memory retract --evidence ...` from
  `sdd/research/202605/sase_dreams_design.md`.

The reducer returns the latest event per `proposal_id`. Tolerate malformed rows the same way
`read_memory_read_events` does (skip + continue), so a corrupt write never blocks listing.

### Reviewer Identity

Approval and rejection both need an auditable reviewer. There is no `require_user_identity()` helper today, so v1
should:

- Default to `getpass.getuser()` for `reviewer_user` and `socket.gethostname()` for `reviewer_host`.
- Set `reviewer_source = "getpass"`.
- Accept `--reviewer NAME` override only when the caller is an agent (e.g., for tests). Reject `--reviewer` outside
  agent context to prevent log forgery from interactive shells.
- Forbid agents from approving their own proposals: if `SASE_AGENT_NAME` is set during `review --approve`, refuse
  and require a human reviewer. This is the most important defense against memory poisoning loops.

## `sase memory write`

Recommended parser behavior (matches the argparse style in `parser_memory.py`):

- Require `--title` (non-empty after `strip()`).
- Require at least one repeatable `--evidence`.
- Require body content from `--file PATH`, `--body TEXT`, or stdin (when stdin is not a TTY).
  `--file` and `--body` are mutually exclusive; `--file -` is equivalent to stdin.
- Require an attributable author. Reuse `require_agent_identity()` from `read_log.py`. Outside an agent context,
  reject by default; allow `--author NAME --author-source manual` only when explicitly opted in so manual capture
  is possible for tests and demos without enabling silent anonymous writes.
- Accept `--keyword` as a repeatable option; reject blank/whitespace-only keywords; deduplicate while preserving
  order.
- Accept `--target long/<slug>.md`, but validate with the same rules `validate_memory_read_path` uses for `long/`:
  relative, no traversal, exactly two path parts, `.md` suffix, lowercase slug `[a-z0-9][a-z0-9_-]*`.
- Accept `--slug SLUG` as a shorthand that becomes `long/<slug>.md`. Mutually exclusive with `--target`.
- If neither `--slug` nor `--target` is given, derive a slug from `--title` (slugify, truncate to 64 chars). Print
  the derived slug back to the user so they can override it.
- Accept `--from-chat CHAT_ID` to carry provenance into the event (needed for the future
  `sase memory retract --evidence <chat_path>` cleanup path).
- Print the proposal id and state path. With `--json`, emit a deterministic JSON record:

  ```json
  {
    "proposal_id": "mem-20260523-142233-a1b2c3d4",
    "status": "pending",
    "target_path": "long/tui_modal_testing.md",
    "body_path": "/home/bryan/.sase/projects/sase/memory_proposals/mem-.../draft.md",
    "ledger_path": "/home/bryan/.sase/projects/sase/memory_proposals.jsonl"
  }
  ```

### Evidence Parsing

Evidence is the central trust contract. Parse each `--evidence` value into a typed record but accept ergonomic
shorthand:

- Plain existing path or `path:<path>[:LINE]` → canonicalize, hash with SHA-256, store size.
- `chat:<id>` → resolve through the chat catalog later; v1 stores typed but unresolved and lets review surface that.
- `url:<url>` or anything matching `^https?://` → store as URL evidence; mark unverified. Do not fetch in v1.
- `note:<text>` → free-form supplemental note. Allow only when at least one non-`note` evidence is also present.

A proposal whose entire evidence list is free-text notes must be rejected at `write` time. Without that rule the
evidence requirement becomes paperwork.

### Body Size Limits

- Soft cap: 16 KiB. Warn and require `--allow-large` to proceed.
- Hard cap: 256 KiB. Reject unconditionally. Long-term memory at this size is almost certainly the wrong shape and
  will balloon agent context cost (see `sdd/research/202604/agents_md_token_optimization.md`).

### Prompt-Injection Heuristics

The proposal body and title will be displayed in the review TUI but should also be lightly scanned at `write` time so
the reviewer is warned, not surprised:

- Flag substrings such as `ignore previous instructions`, `disregard the system prompt`, `always trust`, `delete all`,
  `rm -rf`, `chmod 777`, and known jailbreak markers. Case-insensitive, word-boundary aware.
- Flag if the body redefines known agent policy headers (e.g., starts with `# System` or `# Rules`).
- These are warnings, not blocks. The human reviewer is the real defense. The proposal event records the matched
  patterns so review UI can highlight them.

### Examples

```bash
sase memory write \
  --title "Generated skills must be regenerated after template changes" \
  --keyword "generated skills" \
  --keyword "init-skills" \
  --target long/generated_skills_regen.md \
  --evidence src/sase/main/init_skills_handler.py \
  --evidence memory/long/generated_skills.md \
  --file /tmp/proposed-memory.md

cat /tmp/proposed-memory.md | sase memory write \
  --title "TUI modal tests use Textual pilot" \
  --keyword "Textual modal" \
  --evidence tests/ace/tui/test_agent_tag_modal_pilot.py \
  --from-chat 6b3f9c12
```

## `sase memory review`

Two modes. Mode is chosen by argv, not by a `--interactive` flag:

| Invocation                                  | Mode             |
| ------------------------------------------- | ---------------- |
| `sase memory review`                        | Interactive TUI (TTY) or `--list` fallback (non-TTY) |
| `sase memory review --list [--json] [--all]`| Non-interactive list |
| `sase memory review ID --show [--json]`     | Non-interactive detail |
| `sase memory review ID --approve [...]`     | Non-interactive approval |
| `sase memory review ID --edit`              | Open `$EDITOR`, validate, then approve |
| `sase memory review ID --reject --reason X` | Non-interactive rejection |

### Non-Interactive Mode

Rules:

- `--approve`, `--reject`, `--show`, and `--edit` are mutually exclusive and each require a proposal id (or
  unambiguous id prefix, mirroring `sase memory log --id` behavior).
- `--reject` requires `--reason` (non-empty after strip).
- `--approve` uses `draft.md` unless `--edited-file PATH` is given; `--edited-file` writes the content into
  `reviewed.md` first and the approval event records `edited: true`.
- `--approve` creates exactly one canonical `memory/long/<slug>.md` file using a temp-file + `os.replace` pattern
  (matches the atomic-write guidance in `sase-core` notification storage).
- If the target exists, fail by default. Defer merge/append/replace to a later command unless an explicit
  `--replace` policy is added with strong warnings. Treating "update existing memory" as a separate workflow keeps
  the approval audit trail clean.
- After a successful write, run `build_memory_inventory()` against the project and warn if the new file is only
  `available` (not loaded via `@` reference and not auto-discoverable). The most common cause is missing
  `keywords` frontmatter, which makes `loader_memory.py` skip the file silently.
- Approvals never modify `memory/short/`, `AGENTS.md`, or any instruction shim.

Canonical memory file frontmatter should stay compact:

```yaml
---
keywords:
  - Textual modal
  - run_test
source_candidate: mem-20260523-142233-a1b2c3d4
---
```

Do not embed the full evidence list in the canonical memory file. Dynamic memory loads the full file into the agent
prompt, so provenance bloat has direct context cost. The full evidence record stays in the JSONL ledger and the
proposal directory.

### Interactive Mode (Textual)

`textual[syntax]>=0.45.0` is already a runtime dependency. Build a standalone Textual app launched only when stdout
is a TTY; do not require `sase ace`. This is a focused CLI review surface.

Recommended first screen:

```text
+-- Memory Proposals ---------------------------+-- Proposal -----------------------------+
| pending  age   author       title             | title, target, keywords, evidence count |
| > 1      12m   agent.foo    TUI modal tests   | warnings (injection / target conflict)  |
|   2      1h    agent.bar    Generated skills  | rendered markdown preview               |
|   3      3h    agent.baz    Telegram setup    | inline diff if target exists            |
+-----------------------------------------------+-----------------------------------------+
 j/k move  / filter  enter drill down  a approve  e edit+approve  r reject  q quit
```

Drill-down view:

- Header with id, author, created time, status, target, and conflict warnings.
- Tabbed or left-rail sections: `Memory`, `Evidence`, `Target`, `Audit`.
- `Memory`: Markdown preview plus raw frontmatter/body view.
- `Evidence`: one row per evidence item with verified/unverified status, hash, path, and a small excerpt for path
  evidence (cheap: read first N bytes when `exists_at_proposal_time` is true).
- `Target`: target path status. If the file exists, render a `difflib.unified_diff` preview between current target
  content and the proposal body.
- `Audit`: agent identity block, artifacts dir, cwd, ledger event timestamps, and any prior review action.

Keybindings:

- `j/k`, arrows, `g/G`: navigation.
- `/`: filter proposals by substring (title, author, keyword).
- `enter` or `d`: drill down.
- `escape`: leave drill-down.
- `a`: approve `draft.md` as-is.
- `e`: edit then approve. Suspend Textual, open `$VISUAL`/`$EDITOR` on a copy in `reviewed.md`, re-read on return,
  show the resulting diff, then ask for final approval.
- `r`: open a small modal to collect a rejection reason.
- `o`: open selected evidence in `$EDITOR` or pager.
- `t`: edit target path before approval.
- `y`: copy proposal id.
- `q`: quit.

### Textual Implementation Notes

Pull from the strongest local precedents rather than inventing layouts:

- `src/sase/ace/tui/modals/mentor_review_modal.py` — two-pane review (`Container` + `Horizontal`), explicit
  `BINDINGS`, `_refresh_all()` pattern, side panel for navigation, main panel for content. This is the closest
  match for the drill-down view.
- `src/sase/ace/tui/modals/plan_approval_modal.py` — review-Markdown-with-actions pattern (approve / reject /
  feedback / edit).
- `src/sase/ace/tui/modals/approve_options_modal.py` — compact action chooser with explicit key-event barriers.
- `src/sase/ace/tui/modals/base.py:CopyModeForwardingMixin` — gives `y`-style copy behavior consistently with the
  rest of the TUI; reuse it on the review screen.
- `tests/test_approve_options_modal_keys.py`, `tests/test_mentor_review_modal_actions.py`, and
  `tests/test_ace_tui_app.py` — practical patterns for `App.run_test()` / `Pilot.press` interaction tests.

Widget choices:

- Proposal list: prefer `DataTable` over `OptionList`. `DataTable` supports sortable columns (age, author, target),
  fixed-width columns for status badges, and per-cell styling without custom render code.
  Docs: <https://textual.textualize.io/widgets/data_table/>.
- Body preview: `Markdown` for read-only render, `MarkdownViewer` if a table-of-contents is wanted later. Falling
  back to Rich `Syntax` with the `markdown` lexer (the `MentorReviewModal` pattern) is fine when consistency with
  existing modals matters.
  Docs: <https://textual.textualize.io/widgets/markdown/>.
- In-app editor: `Textual TextArea` exists and supports syntax highlighting via the `textual[syntax]` extra, but for
  v1 prefer `$EDITOR` for serious markdown edits — wrapping, search, and user muscle memory all favor it. The TUI
  should suspend with `App.suspend()`, open the editor on a temp copy, reload, show the diff, then prompt for final
  approval. Docs: <https://textual.textualize.io/widgets/text_area/>.
- Tests: Textual's official testing guide covers `App.run_test()` and `Pilot.press` / `Pilot.click`, plus optional
  SVG snapshot testing. <https://textual.textualize.io/guide/testing/>.

Do not bury proposal logic in widget methods. Keep the storage/reducer pure and Textual-free:

- `src/sase/memory/proposals.py` — domain model, id generation, path validation, evidence parsing, ledger
  append/read/reduce, approve/reject/edit transitions. No `textual`/`rich` imports.
- `src/sase/memory/cli_write.py` — parser-facing `write` handler.
- `src/sase/memory/cli_review.py` — non-interactive review handler and Textual launch dispatch.
- `src/sase/memory/review_tui.py` — standalone Textual app, screens, key bindings.
- `src/sase/memory/identity.py` (optional refactor) — shared agent + reviewer identity helpers, extracted from
  `read_log.py` if the duplication grows.

## Comparator Snapshot

For the propose/review slice specifically:

| System              | Agent-proposes | Required evidence | Human review gate | Drill-down review UI | Audit log |
| ------------------- | -------------- | ----------------- | ----------------- | -------------------- | --------- |
| Claude Code         | no (file edits) | n/a              | n/a               | no                   | partial   |
| Letta MemFS         | yes            | no                | configurable      | tree view            | git-based |
| Basic Memory        | yes (MCP)      | no                | optional          | partial              | yes       |
| Goose memory ext.   | yes (tool)     | no                | no                | no                   | partial   |
| Mem0 / Zep          | yes (API)      | no                | dashboard         | dashboard            | varies    |
| OpenHands skills    | n/a            | n/a               | n/a               | no                   | no        |
| **Proposed SASE**   | **yes (CLI)**  | **yes (>=1)**     | **mandatory**     | **Textual TUI**      | **JSONL** |

The required-evidence column is the clearest differentiator. None of the comparators force agents to provide
evidence at proposal time, and none combine a mandatory human review gate with a beautiful terminal review surface.
Together those two are the v1 thesis.

## Integration with Adjacent Subsystems

`memory log`: extend `sase memory log` to optionally include proposal/review events (`--include proposals`) so the
same command answers "what has happened to this project's long-term memory?" without users learning a second
inspection surface. Default to read-only events to preserve current behavior.

`sase notify`: on a successful `write`, optionally append a `memory.proposed` notification via the existing
`append_notification()` API in `src/sase/notifications/store.py`. The notification action data should carry
`proposal_id` so a TUI/mobile notification can deep-link into `sase memory review <id> --show`. Make the
notification best-effort — failures must not block proposal creation.

Telemetry: add three counters to `src/sase/telemetry/metrics.py`:

- `MEMORY_PROPOSALS_PROPOSED`
- `MEMORY_PROPOSALS_APPROVED` (labeled `edited=true|false`)
- `MEMORY_PROPOSALS_REJECTED`

These are the leading indicators for the v2 "is the memory pool actually growing?" question raised in
`sdd/research/202604/dynamic_memory_critique.md`.

Hooks: do not add new hook event types in v1. The current `src/sase/ace/hooks/` registry has no memory events;
adding them deserves its own design (see `sase_memory_command_subcommands.md`). Proposals create no agent runtime
state, so this can wait.

`sase memory retract --evidence <chat>` (future): the `from_chat` field on the event row is what makes this command
work later. A retraction will scan approved events for `from_chat == <id>` and propose canonical-memory removal.
Recording it now is cheap and unblocks that work.

## Concurrency, Crashes, and Edge Cases

- **Concurrent proposers.** Multiple agents may call `write` simultaneously. The JSONL append is guarded by the
  same `_locked(...fcntl.LOCK_EX)` helper as `memory_reads.jsonl`. Per-proposal directory creation is
  `mkdir(parents=True, exist_ok=False)` with the proposal id including a random suffix to avoid collisions.
- **Concurrent reviewers.** Two reviewers approving the same proposal will both append `approved` events; the
  reducer picks the latest by timestamp. The canonical-memory file write should use `O_CREAT|O_EXCL` so the second
  reviewer's write fails loudly instead of clobbering the first.
- **Crash during write.** The body file is written before the event is appended. If the agent crashes before
  appending the event, an orphan directory exists with no ledger entry. A periodic `sase memory doctor` check
  (future) can list and prune orphans.
- **Crash during approval.** Write the canonical file first (with `O_CREAT|O_EXCL`), then append the `approved`
  event. If the event append fails, the file exists but is unattributed; the next `review --list` will still show
  the proposal as `pending`. Document that double-approval will fail because the file already exists, which is
  acceptable for v1.
- **Agent identity spoofing.** Agents can set `SASE_AGENT_NAME` arbitrarily today. v1 cannot prevent that. Mitigate
  by surfacing `agent_source` in the review UI so reviewers can see whether identity came from `agent_meta.json`
  (strongest), `SASE_AGENT_NAME` (weaker), or manual override (weakest).
- **Stale target on approval.** Between proposal time and approval time, the canonical target may have been created
  by another path. The default fail-if-exists behavior surfaces this; the reviewer can change `--target`.

## Phased Implementation

### Phase 1 — Storage + `write`

- `src/sase/memory/proposals.py` with frozen dataclasses for `ProposalEvent` and `ProposalState`, reducer, JSONL
  append/read helpers reusing `read_log._locked`, id generation, path/slug/keyword validation, evidence parsing.
- `src/sase/memory/cli_write.py` thin handler.
- Parser entry in `parser_memory.py` and dispatch in `memory_handler.py`.
- Body files written under `~/.sase/projects/<project>/memory_proposals/<id>/draft.md`.
- Unit tests: validation, evidence parsing, identity requirement, size limits, injection heuristics, JSONL append
  and reducer.

### Phase 2 — Non-Interactive `review`

- `--list`, `--show`, `--approve`, `--reject`, `--edit` modes.
- Canonical-memory write with `O_CREAT|O_EXCL` + atomic temp swap.
- Reachability warning via `build_memory_inventory()` after approval.
- `--json` output for every mode.
- CLI tests covering id-prefix resolution, mutually-exclusive flags, agent-self-approval refusal.

### Phase 3 — Textual Review App

- `src/sase/memory/review_tui.py` modeled on `mentor_review_modal.py`.
- `DataTable` proposal list, `Markdown` preview, drill-down sections, diff preview against existing targets.
- `Pilot` tests for navigation, drill-down, approve/reject callbacks against a temp ledger.
- No visual-snapshot requirement in v1; add later if the UI becomes part of the ACE visual snapshot suite.

### Phase 4 — Polish and Integration

- `sase memory log --include proposals` extension.
- Optional `memory.proposed` notification on write.
- Telemetry counters.
- Docs: `docs/init.md`, `docs/cli.md`, `docs/configuration.md`, parser epilog examples.
- Run `just install && just check` for source changes.

## Tests

Focused tests to add at minimum (matching existing repo patterns):

- Parser registers `write` and `review`; `write` requires `--evidence`; review action flags are mutually exclusive.
- `write` rejects traversal targets, nested long paths, missing content, blank evidence, free-text-only evidence,
  oversize bodies, and unattributed agent writes.
- `write` creates a proposal with hashed file evidence and stable, sort-keys JSON.
- Reducer correctly reduces multi-event ledgers to current state and ignores malformed rows.
- `review --json --list` is deterministic across runs.
- `review --reject --reason ...` updates status and preserves draft/evidence.
- `review --approve` writes `memory/long/<slug>.md` with compact frontmatter, refuses existing targets, and warns
  on unreachable memory after write.
- `review --approve --edited-file ...` writes the edited content and records `edited: true`.
- `review --approve` refuses when `SASE_AGENT_NAME` is set (agent-self-approval guard).
- Textual `Pilot` tests cover opening the TUI, moving selection, drill-down, dispatching approve/reject callbacks,
  and editor-suspend roundtrip against a temp proposal store.

## Risks

- **Memory poisoning** — solved by `write` being proposal-only, required evidence, mandatory human promotion, and
  the agent-self-approval guard. Do not add auto-approve in v1.
- **Ephemeral workspace loss** — solved by storing proposals under `~/.sase/projects/<project>/`, not `.sase/`.
- **Context bloat** — solved by compact canonical frontmatter, body size caps, and keeping full evidence out of
  `memory/long/*.md`.
- **Silent target conflicts** — fail approval when target exists. Merging with existing memory is a separate
  command that deserves its own UX design.
- **Unverifiable evidence** — surface it prominently in review and refuse free-text-only proposals at write time.
- **Cross-frontend drift** — design the JSONL row schema now as a future core wire contract, even before Rust owns
  it. Per `memory/short/rust_core_backend_boundary.md`, any frontend that grows a need for proposal listing
  (Telegram, mobile, nvim) should drive moving the storage/reducer to `sase-core`.
- **Memory invisibility after approval** — caught by the post-approval reachability check warning when the new
  long-memory file lacks `keywords` frontmatter, since `loader_memory.py` silently ignores those.
- **Reviewer log forgery** — mitigated by refusing `--reviewer` overrides outside agent context.

## Open Questions

1. Should non-agent users be able to run `sase memory write` for manual capture, or should proposal creation be
   strictly agent-only? Recommendation: allow explicit `--author NAME --author-source manual`, but never anonymous
   writes; document that manual proposals are for tests and demos.
2. Should URL evidence be fetched and hashed? Recommendation: not in v1. Store as unverified; let the reviewer
   decide; add `--fetch-urls` later when network policy is settled.
3. Should approvals support appending to an existing memory file? Recommendation: not in v1. Update-existing is a
   semantically different workflow and deserves its own command (`sase memory update <path>` proposing a patch).
4. Should `write` always create a SASE notification? Recommendation: opt-in via `--notify` in v1; flip the default
   once the notification UX is proven not to be noisy.
5. Should canonical memory frontmatter include full evidence? Recommendation: no by default; keep evidence in the
   ledger and include only `source_candidate: <proposal_id>` in the memory file.
6. Should `--edit` use Textual `TextArea` instead of `$EDITOR`? Recommendation: `$EDITOR` first; consider
   `TextArea` only after real user feedback says the editor suspend is awkward.
7. Should `sase memory log` show proposal/review events by default? Recommendation: no — gate behind
   `--include proposals` to avoid breaking the existing read-log focus, but make `sase memory review --list` the
   canonical surface for proposal state.
8. Should the proposal id format encode date/time, or be pure random? Recommendation: keep the
   `mem-YYYYMMDD-HHMMSS-<8 hex>` format from the draft for human sortability; uniqueness comes from the suffix.

## Sources

Local repo:

- `src/sase/main/parser_memory.py`
- `src/sase/main/memory_handler.py`
- `src/sase/memory/read_log.py`
- `src/sase/memory/cli_read.py`
- `src/sase/memory/cli_list.py`
- `src/sase/memory/inventory.py`
- `src/sase/xprompt/loader_memory.py`
- `src/sase/ace/tui/modals/mentor_review_modal.py`
- `src/sase/ace/tui/modals/plan_approval_modal.py`
- `src/sase/ace/tui/modals/approve_options_modal.py`
- `src/sase/ace/tui/modals/base.py`
- `src/sase/notifications/store.py`
- `src/sase/main/notify_handler.py`
- `memory/short/rust_core_backend_boundary.md`
- `memory/short/gotchas.md`
- `sdd/research/202605/sase_memory_command_subcommands.md`
- `sdd/research/202605/sase_memory_command_research.md`
- `sdd/research/202605/sase_memory_write_review_research.md`
- `sdd/research/202605/zettel_sase_shared_memory.md`
- `sdd/research/202605/sase_dreams_design.md`
- `sdd/research/202604/dynamic_memory_critique.md`
- `sdd/research/202604/agents_md_token_optimization.md`
- `sdd/epics/202605/memory_read_log.md`

External:

- [Textual: DataTable](https://textual.textualize.io/widgets/data_table/)
- [Textual: Markdown](https://textual.textualize.io/widgets/markdown/)
- [Textual: TextArea](https://textual.textualize.io/widgets/text_area/)
- [Textual: Testing](https://textual.textualize.io/guide/testing/)
- [Claude Code: Memory](https://code.claude.com/docs/en/memory)
- [Letta Code: MemFS](https://docs.letta.com/letta-code/memfs)
- [Basic Memory: CLI reference](https://docs.basicmemory.com/reference/cli-reference)
- [Goose: Memory extension](https://block.github.io/goose/docs/tutorials/memory-extension)
- [Mem0 docs](https://docs.mem0.ai/)
