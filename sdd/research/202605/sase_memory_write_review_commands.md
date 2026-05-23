---
create_time: 2026-05-23
status: research
---

# `sase memory write` and `sase memory review`

## Question

How should SASE implement two new `sase memory` commands so agents can propose new long-term memories with evidence, and
users can review, reject, approve, or approve with edits from both non-interactive CLI flags and a high-quality terminal
review UI?

## Recommendation

Implement `sase memory write` as an **agent proposal capture** command, not a direct writer to `memory/long/*.md`.
Implement `sase memory review` as the only command that can promote a proposal into canonical long-term memory.

Recommended v1 command surface:

```bash
sase memory write --title TITLE --evidence EVIDENCE [--evidence EVIDENCE ...] \
  [--target long/topic.md] [--keyword KW ...] [--file draft.md] [--json]

sase memory review
sase memory review [PROPOSAL_ID]
sase memory review PROPOSAL_ID --approve [--target long/topic.md] [--edited-file edited.md]
sase memory review PROPOSAL_ID --reject --reason "Not durable or not supported"
sase memory review --json [--all]
```

The important product rule: `write` creates a reviewable proposal under SASE state. It never modifies `memory/short/` or
`memory/long/`. `review --approve` is the first point where canonical repo files change.

## Current Local State

The current `sase memory` command group already exists:

- `src/sase/main/parser_memory.py` registers `init`, `list`, `read`, and `log`.
- `src/sase/main/memory_handler.py` dispatches those subcommands.
- `src/sase/memory/cli_list.py` renders a Rich memory dashboard.
- `src/sase/memory/cli_read.py` reads only `memory/long/*.md`, strips leading YAML frontmatter, and appends an
  attributable audit log event.
- `src/sase/memory/read_log.py` stores read events as JSONL under `~/.sase/projects/<project>/memory_reads.jsonl` with
  file locking.
- `src/sase/memory/inventory.py` understands loaded, referenced, available, and missing memory files across project and
  home context roots.

That gives two strong implementation precedents:

1. Agent-initiated memory operations should be attributable, as `read` already requires.
2. Project-scoped memory audit state already belongs under `~/.sase/projects/<project>/`, not inside the ephemeral
   workspace clone.

Dynamic long-term memory discovery is still file-based:

- `src/sase/xprompt/loader_memory.py` auto-discovers top-level `memory/long/*.md` files only when they have `keywords`
  frontmatter.
- It uses `glob("*.md")`, not recursive discovery, so v1 approvals should target `long/<slug>.md`, not nested paths.
- `src/sase/memory/dynamic.py` injects matched long-term memory into `.sase/memory/` during agent launch.

The sibling Rust core currently has xprompt catalog support for memory entries, but no memory proposal/review API. Per
`memory/short/rust_core_backend_boundary.md`, the proposal data model should be designed as a stable wire shape so it
can move to `sase-core` later, even if the first CLI implementation is Python-only.

## Why State Should Not Live in the Workspace

Earlier memory research left open whether proposals should live in `.sase/memory/inbox/` or project-local state. For
this specific `write` command, the right answer is `~/.sase/projects/<project>/memory_proposals/`.

Reasons:

- SASE agents run in numbered, ephemeral workspace clones. A proposal written to `.sase/memory/inbox/` inside an agent
  clone can be invisible from the user's normal review workspace.
- The existing read audit log already uses `~/.sase/projects/<project>/memory_reads.jsonl`.
- Proposal files are not canonical memory and should not dirty the user's repo before review.
- A project-scoped state path lets multiple agents propose concurrently and lets a user review from any workspace for
  that project.

Recommended storage:

```text
~/.sase/projects/<project>/memory_proposals/
  proposals.lock
  202605/
    mem-20260523-142233-a1b2c3d4/
      proposal.json
      draft.md
      reviewed.md        # present only after approval with edits
```

Use a per-project lock for create and state transitions. Use temp files plus `os.replace()` for JSON rewrites, matching
existing notification and ChangeSpec storage patterns.

## Proposal Schema

Use one directory per proposal. Keep the body as markdown so external editors and the TUI can work with it naturally.

Suggested `proposal.json` shape:

```json
{
  "schema_version": 1,
  "id": "mem-20260523-142233-a1b2c3d4",
  "project": "sase",
  "created_at": "2026-05-23T18:22:33+00:00",
  "updated_at": "2026-05-23T18:22:33+00:00",
  "status": "pending",
  "title": "TUI modal pilot tests use Textual run_test",
  "suggested_path": "long/tui_modal_testing.md",
  "keywords": ["Textual modal", "run_test", "pilot test"],
  "body_path": "draft.md",
  "body_sha256": "sha256:...",
  "author": {
    "name": "agent-name",
    "source": "SASE_AGENT_NAME",
    "artifacts_dir": "/home/bryan/.sase/projects/sase/artifacts/..."
  },
  "cwd": "/home/bryan/.local/state/sase/workspaces/sase-org/sase/sase_10",
  "evidence": [
    {
      "kind": "file",
      "value": "tests/ace/tui/test_agent_tag_modal_pilot.py",
      "resolved_path": "/abs/path/tests/ace/tui/test_agent_tag_modal_pilot.py",
      "sha256": "sha256:...",
      "byte_count": 1234,
      "exists": true
    }
  ],
  "review": null
}
```

On approval, rewrite `proposal.json` with:

```json
{
  "status": "approved",
  "review": {
    "decision": "approved",
    "reviewed_at": "2026-05-23T18:40:00+00:00",
    "reviewer": "bryan",
    "target_path": "memory/long/tui_modal_testing.md",
    "edited": true,
    "approved_body_path": "reviewed.md",
    "approved_body_sha256": "sha256:..."
  }
}
```

For rejection, store a non-empty reason. Do not delete rejected proposals; they are security and quality evidence.

## `sase memory write`

Recommended parser behavior:

- Require at least one repeatable `--evidence`.
- Require content from `--file` or stdin.
- Require an attributable author. Auto-detect with the existing memory-read identity logic
  (`SASE_AGENT_NAME`, `SASE_AGENT`, or `SASE_ARTIFACTS_DIR/agent_meta.json`). Outside an agent, require an explicit
  `--author` if manual proposal creation is desired.
- Accept `--keyword` as a repeatable option; reject blank keywords.
- Accept `--target long/<slug>.md`, but validate that it is a relative top-level `long/*.md` path with no traversal.
- Print the proposal id and state path. With `--json`, emit deterministic machine-readable JSON.

Recommended examples:

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
  --evidence tests/ace/tui/test_agent_tag_modal_pilot.py
```

Evidence parsing should be typed but ergonomic:

- Plain existing path or `path:<path>` -> canonicalize, hash, store size.
- `chat:<ref>` -> resolve through the chat catalog later; v1 may store as typed but unresolved if resolver wiring is too
  large.
- `url:<url>` or `https://...` -> store as URL evidence, but mark it unverified unless a future fetch-and-hash step is
  added.
- `note:<text>` -> allow only as supplemental evidence, not as the sole evidence in v1.

The command should reject proposals where every evidence entry is unverifiable free text. That keeps the "evidence"
requirement meaningful for agent proposals.

## `sase memory review`

The review command has two modes.

### Non-Interactive Mode

When an action flag is supplied, do not start Textual:

```bash
sase memory review mem-20260523-142233-a1b2c3d4 --approve
sase memory review mem-20260523-142233-a1b2c3d4 --approve --target long/new_slug.md
sase memory review mem-20260523-142233-a1b2c3d4 --approve --edited-file /tmp/reviewed.md
sase memory review mem-20260523-142233-a1b2c3d4 --reject --reason "Already documented"
```

Rules:

- `--approve`, `--reject`, and `--json` list output should be mutually clear. An action requires a proposal id.
- Rejecting requires `--reason`.
- Approving uses `--edited-file` content when provided, otherwise `draft.md`.
- Approving creates exactly one canonical `memory/long/<slug>.md` file.
- If the target exists, fail by default. Defer merge/append/replace to a later command unless an explicit `--replace`
  policy is added with strong warnings.
- Use a temp file and atomic replace for the proposal status update. For the canonical memory file, prefer fail-if-exists
  creation so two approvals cannot clobber each other.

Canonical memory frontmatter should stay compact:

```yaml
---
keywords:
  - Textual modal
  - run_test
source_candidate: mem-20260523-142233-a1b2c3d4
---
```

Do not embed the full evidence list in canonical memory by default. Dynamic memory may load the full file into an agent
prompt, so provenance bloat has direct context cost. The full evidence record remains in the proposal archive.

### Interactive Mode

With no action flags, run a standalone Textual app. Do not require `sase ace`; this is a focused CLI review surface.

Use existing dependencies and patterns:

- `textual` is already a runtime dependency.
- Existing TUI code already uses modal drill-down, vim-style navigation, styled footers, side panels, and pilot tests.
- `PromptHistoryModal`, `AgentArtifactSelectionModal`, and `MentorReviewModal` are the closest local design precedents.

Recommended first screen:

```text
+-- Memory Proposals ---------------------------+-- Proposal ----------------------------+
| pending  age  author       title              | title, target, keywords, evidence     |
| > 1      12m  agent.foo    TUI modal tests    | warnings/conflicts                    |
|   2      1h   agent.bar    Generated skills   | rendered markdown preview             |
+-----------------------------------------------+----------------------------------------+
  j/k move  / filter  enter drill down  a approve  e edit+approve  r reject  q quit
```

Recommended drill-down view:

- Header with id, author, created time, status, target, and conflict warnings.
- Left or top navigation for sections: `Memory`, `Evidence`, `Target`, `Audit`.
- `Memory`: Markdown preview plus raw frontmatter/body view.
- `Evidence`: one row per evidence item, with verified/unverified status, hash, path, and excerpt if cheap.
- `Target`: shows target path status and a diff-like preview of the file that will be created.
- `Audit`: author metadata, artifacts dir, cwd, timestamps, and previous review action if already decided.

Keybindings:

- `j/k`, arrows, `g/G`: navigation.
- `/`: filter proposals.
- `enter` or `d`: drill down.
- `esc`: leave drill-down.
- `a`: approve original draft.
- `e`: edit then approve.
- `r`: reject with reason.
- `o`: open selected evidence in `$EDITOR` or pager.
- `t`: edit target path before approval.
- `y`: copy proposal id.
- `q`: quit.

For manual edits, prefer `$EDITOR` in v1 over building a full in-TUI markdown editor. Textual `TextArea` exists and can
be used later, but `$EDITOR` is more reliable for multi-line markdown, wrapping, search, and user muscle memory. The
TUI should pause, open a temp copy, re-read it, show the resulting diff, then ask for final approval.

## Implementation Shape

Add these modules:

- `src/sase/memory/proposals.py`: domain model, id generation, path validation, evidence parsing, create/list/load,
  approve/reject transitions.
- `src/sase/memory/cli_write.py`: parser-facing `write` handler.
- `src/sase/memory/cli_review.py`: non-interactive review handler and Textual launch.
- `src/sase/memory/review_tui.py`: standalone Textual app and screens.

Update:

- `src/sase/main/parser_memory.py`: register `write` and `review`.
- `src/sase/main/memory_handler.py`: dispatch `write` and `review`.
- `docs/init.md`, `docs/cli.md`, and `docs/configuration.md`: document the workflow.
- `memory/README.md`: mention proposals only after implementation, not during research.

Refactor:

- Move agent identity helpers from `sase.memory.read_log` to a small shared module such as `sase.memory.identity`, or
  keep wrappers in `read_log.py` and import them initially. Avoid duplicating environment probing.

Keep v1 Python-only. The schema should be rectangular and JSON-friendly so a future `sase-core` API can take ownership
without changing user-visible behavior.

## Tests

Recommended focused tests:

- Parser registers `write` and `review`; `write` requires `--evidence`; review action flags are mutually exclusive.
- `write` rejects traversal targets, nested long paths, missing content, blank evidence, and unattributed agent writes.
- `write` creates a proposal with hashed file evidence and stable JSON.
- `review --json` lists pending proposals and resolves id prefixes with missing/ambiguous errors.
- `review --reject --reason ...` updates status and preserves draft/evidence.
- `review --approve` creates `memory/long/<slug>.md` with compact frontmatter and refuses existing targets.
- `review --approve --edited-file ...` writes the edited content and records `edited: true`.
- Textual pilot tests cover opening the TUI, moving selection, drill-down, and dispatching approve/reject callbacks
  against a temp proposal store.

No visual snapshot test is required for v1 unless the UI becomes part of the ACE visual snapshot suite. A small
Textual `run_test()` pilot is enough to protect keybindings and drill-down behavior.

## Risks

- **Memory poisoning:** solved by `write` being proposal-only, required evidence, and human promotion. Do not add
  auto-approve in v1.
- **Ephemeral workspace loss:** solved by storing proposals under `~/.sase/projects/<project>/`, not `.sase/`.
- **Context bloat:** solved by compact canonical frontmatter and by keeping full evidence out of `memory/long/*.md`.
- **Silent target conflicts:** fail approval when target exists. Merging with an existing memory needs a separate,
  more deliberate UX.
- **Unverifiable evidence:** surface it loudly in review and reject free-text-only proposals.
- **Cross-frontend drift:** design the JSON schema now as a future core wire contract, even before Rust owns it.

## Open Questions

1. Should a user be able to run `sase memory write` outside an agent with `--author`, or should proposal creation be
   agent-only? Recommendation: allow explicit `--author` for tests and manual capture, but never anonymous writes.
2. Should URL evidence be fetched and hashed? Recommendation: not in v1. Store URL evidence as unverified and let the
   reviewer decide.
3. Should approvals support appending to an existing memory file? Recommendation: not in v1. Existing-file merges are
   semantically different from proposing a new long-term memory.
4. Should `write` create a SASE notification? Recommendation: optionally append a simple notification after the store is
   reliable, but do not block the command on notification support.
5. Should canonical memory frontmatter include full evidence? Recommendation: no by default; keep the full evidence in
   the proposal archive and only include `source_candidate` in the memory file.
