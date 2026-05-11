# User-Authored File Line Comments

Date: 2026-05-11

## Question

We want a way for a human user to review an arbitrary file, attach comments to specific lines as they read, and have
those comments land in the **same on-disk format that mentor agents already produce**. What's the best way to
implement that?

The deliverable is a recommendation, not an implementation — this doc captures the existing comment format, the
infrastructure we can reuse, the open design questions, and the option set with tradeoffs.

---

## TL;DR

- The canonical comment artifact is already nailed down: a JSON file matching `MENTOR_OUTPUT_JSON_SCHEMA`
  (`comments: [{focus_name, file_path, line_number, description, severity}]`), written to
  `~/.sase/comments/<name>-<reviewer>-<ts>.json`, and pointer-registered in the ChangeSpec `COMMENTS` drawer of a `.gp`
  file. We do **not** need to invent a format.
- The interesting decisions are: **where the user enters the comment** (TUI file viewer vs `$EDITOR` vs pure CLI),
  **what reviewer name to use**, **how (or whether) to bind a comment to a ChangeSpec**, and how to handle
  **multi-line / code-range comments** (mentor format only models a single `line_number`).
- Recommendation (Option C below): build a **TUI file viewer with a `c` "comment-on-line" hotkey** that opens a modal
  whose body is composed in `$EDITOR` (multi-line), wraps the result as a `MentorComment` with `reviewer="user"` (or
  `reviewer=<git user.email local-part>`), batches all comments from one review session into a single JSON file, and
  registers it in the COMMENTS drawer of the active ChangeSpec.

The rest of this document supports that recommendation.

---

## Background: how mentor comments work today

### Canonical data shape

`src/sase/ace/mentor_output.py:18-25`:

```python
@dataclass
class MentorComment:
    focus_name: str
    file_path: str
    line_number: int
    description: str
    severity: str  # "error" | "warning" | "suggestion"
```

JSON schema (`MENTOR_OUTPUT_JSON_SCHEMA`, same file, lines 40-68):

```json
{
  "comments": [
    {
      "focus_name": "string",
      "file_path": "string",
      "line_number": 42,
      "description": "string",
      "severity": "error|warning|suggestion"
    }
  ]
}
```

Validated and previewed via the existing CLI: `sase comments <file>` (`src/sase/main/comments_handler.py:25-67`)
already runs `jsonschema.validate(...)` against this schema and exits non-zero on failure — so any new producer of
"user comments" should round-trip cleanly through `sase comments` for free.

### On-disk layout

- Per-output JSON: `~/.sase/comments/<name>-<reviewer>-<YYmmdd_HHMMSS>.json` (`src/sase/ace/comments/core.py:14-28`).
- ChangeSpec drawer: `.gp` files contain a `COMMENTS:` section whose lines look like
  `  [<reviewer>] <path-to-json> [- (<suffix>)]` (`src/sase/ace/comments/operations.py:12-52`).
- The `CommentEntry` dataclass models that line (`src/sase/ace/changespec/models.py:382-403`):

```python
@dataclass
class CommentEntry:
    reviewer: str            # e.g., "critique", "mentor_<name>"
    file_path: str           # path to the comments JSON
    suffix: str | None       # timestamp / "ZOMBIE" / "Unresolved Critique Comments"
    suffix_type: str | None  # "error", "running_agent", ...
```

Everything in the TUI that displays comments — `src/sase/ace/tui/widgets/comments_builder.py` and
`src/sase/ace/tui/modals/mentor_review_modal.py` — operates on these two artifacts (the JSON and the `CommentEntry`),
not on the producer. So a new producer that emits both gets the existing review/accept/apply pipeline for free.

### Mentor agent producer flow

1. `sase mentor <profile>:<mentor>` (`src/sase/workflows/mentor.py:222-420`) renders `xprompts/mentor.yml` and runs an
   LLM agent.
2. The agent's instructions tell it to write candidate JSON to a tmp file and run `sase comments <file>` to validate
   before returning (`src/sase/xprompts/mentor.yml:52-56`).
3. The workflow parses the response, calls `save_mentor_output()` to land the JSON under `~/.sase/mentors/...`, and
   updates the ChangeSpec MENTORS field (`src/sase/axe/mentor_runner.py:31-150`).
4. Comments referenced from the MENTORS line ultimately surface in the TUI via `MentorReviewModal`, which already
   supports `space` (toggle accept), `a` / `A` (apply + propose / commit), `n`/`p` navigation, etc.

The user-facing path is therefore **already built downstream of the JSON**. Our job is only to add a **second
producer** that writes the same artifact from human input.

---

## What we'd need to build vs. reuse

| Concern                            | Reuse / Already exists                                                                               | New work                                                  |
| ---------------------------------- | ---------------------------------------------------------------------------------------------------- | --------------------------------------------------------- |
| JSON schema + validation           | `MENTOR_OUTPUT_JSON_SCHEMA`, `sase comments`                                                         | None                                                      |
| Comments JSON storage              | `~/.sase/comments/<name>-<reviewer>-<ts>.json`                                                       | None (just write the file)                                |
| ChangeSpec `COMMENTS:` registration | `add_comment_entry()` in `src/sase/ace/comments/operations.py`, `CommentEntry` model                 | Decide which ChangeSpec, decide reviewer name, call API   |
| TUI display of comments            | `comments_builder.py`, `MentorReviewModal`, `comments_handler.py` rich rendering                     | None (works as soon as the entry is registered)           |
| Apply / accept / propose / commit  | Mentor review modal + `_launch_mentor_apply_agent()` (`actions/agent_workflow/_mentor_review.py`)    | None (no-op — user comments may or may not be "applied")  |
| File viewing UI                    | `AgentFilePanel` (`src/sase/ace/tui/widgets/file_panel/__init__.py:1-531`), syntax highlighting map  | A **read-with-line-numbers** view focused on review       |
| Comment composition                | `$EDITOR` invocation pattern (`actions/agents/_panel_detail.py:103-140`), tmpfile pattern (lines 131-139) | Glue: line number capture + multi-line body editor    |
| Keymap registration                | `default_config.yml` + `keymaps/types.py`                                                            | One new binding (e.g. `c` in the new viewer)              |
| CLI surface                        | `sase comments` (read), nothing for write                                                            | A small `sase comment add` (or `sase review`) producer    |

The takeaway: the **plumbing is done**. The new code is mostly an entry-experience question.

---

## Open design questions

These are the choices that materially shape the implementation. Each option section below picks one combination of
answers; the user should weigh in (see "Open questions for the user" at the end).

1. **Entry surface**: TUI file viewer? `$EDITOR`-driven? Pure CLI? Hybrid?
2. **ChangeSpec coupling**: must the user be inside a CL context to comment, or can comments live free-floating on
   any file in the repo?
3. **Reviewer identity**: `"user"` (single bucket, simple), `<git user.email local-part>` (per-author), configurable
   via `~/.config/sase/sase.yml`?
4. **Single comment vs. session batch**: each comment its own JSON file (matches mentor's "1 mentor run = 1 file"), or
   one JSON per review session that accumulates as the user goes?
5. **Schema gaps**: mentor format only has `line_number` (singular) and a fixed `severity` enum. User comments
   plausibly want **line ranges** ("lines 40–47") and **freeform tags** instead of `severity`. Do we extend the
   schema or fit awkwardly into it?
6. **Focus area**: mentor's `focus_name` is the focus area from the mentor profile. For a user, what fills this
   slot — a free-text tag the user types? A fixed string like `"user_review"`? Optional?
7. **Apply pipeline**: should user comments flow through the same "accept → apply via agent" pipeline as mentor
   comments, or are they purely informational?

---

## Implementation options

### Option A — Pure CLI

`sase comment add <file>:<line> -m "body" [-s warning] [-f general]` writes/updates a JSON file and registers it in
the active ChangeSpec.

- **Pros**: smallest surface, scriptable, easy to test, works over SSH without a TUI.
- **Cons**: writing many comments one at a time is tedious; no visual context (you can't "see what you're commenting
  on" without flipping windows); composing a multi-line body on a CLI flag is awkward (`-m` shells get clunky for
  paragraphs).
- **Variant A2**: drop the `-m` and always pop `$EDITOR` for the body. Removes the multi-line pain but keeps the
  one-comment-per-invocation friction.
- **Good for**: power users who already have the file open in a separate editor and just want a thin write path.
- **When to pick**: as a **complement** to a richer entry path, or as the v0 if we want to ship in a day.

### Option B — Inline file markers

User edits the file directly and inserts a special marker (e.g. `# sase-comment: severity=warning :: body text`); a
`sase review harvest <file>` command scans for them, builds the JSON, and strips the markers.

- **Pros**: zero new UI; works in any editor; line numbers are implicit in marker position.
- **Cons**: pollutes the file with edits the user must remember to strip; doesn't work for binary or read-only files;
  multi-line bodies are awkward to encode; can't comment on third-party / vendored files cleanly; conflicts with
  formatters and pre-commit hooks; line numbers shift if user edits other parts of the file before harvesting.
- **When to pick**: never as the primary path. Could be a niche supplement for "I'm already editing this file
  anyway." Not recommended.

### Option C — TUI file viewer + `$EDITOR` for the body **(recommended)**

Add a new TUI screen that displays a file with line numbers and syntax highlighting (reusing `_EXTENSION_TO_LEXER`
from `file_panel/_messages.py`). Cursor / `j`/`k` navigates lines. Hotkey `c` on the current line suspends the TUI,
opens a tmpfile in `$EDITOR` for the comment body (reusing the existing pattern at
`actions/agents/_panel_detail.py:131-139`), and on save:

1. Wraps the body as a `MentorComment(focus_name=…, file_path=…, line_number=current_line, description=body, severity=…)`.
2. Appends to (or starts) a session JSON at `~/.sase/comments/<changespec>-user-<session_ts>.json`.
3. Calls `add_comment_entry(changespec_name, CommentEntry(reviewer="user", file_path=<json>, suffix=None))` once at
   session start, so the COMMENTS drawer entry is created on the first comment and reused thereafter.

Entry points:

- TUI: a new global keybinding (e.g. `,r` "review" in leader mode → opens a file picker → opens the viewer).
- CLI: `sase review <file>` opens the viewer directly on a file path (for `sase review path/to/file.py:42`-style
  invocation).
- Optionally also expose Option A as a non-interactive shortcut.

Severity / focus_name: the modal that wraps `$EDITOR` first prompts for severity (single-key: `e`/`w`/`s`) and
optionally a focus tag (default `"user_review"`). Skip the prompt and use `(suggestion, "user_review")` as the
default if the user hits `c c` (double-tap).

- **Pros**: matches the existing mentor review experience aesthetically; gets visual context; uses `$EDITOR` for the
  hard part (multi-line typing) without rebuilding a textarea in Textual; reuses ~all existing infra; one new screen
  + one new modal + one CLI subcommand.
- **Cons**: most code to write of the three options; needs us to nail down the keybinding (see "claimed keys" below);
  Textual `suspend()` round-trip is jarring on slow terminals.
- **Cost estimate**: ~2-3 days for an experienced TUI contributor — viewer screen, modal, CLI entry, JSON writer,
  ChangeSpec drawer wiring, keymap, tests.

### Option D — `$EDITOR`-only (no TUI viewer)

`sase review <file>` opens the file in `$EDITOR` immediately, then on exit scans the editor's "marks" or a sidecar
file the user wrote to during the session and harvests comments.

- **Pros**: leverages the user's existing editor (nvim, vscode-via-cli, etc.) — no new viewer to learn.
- **Cons**: protocol is editor-specific (nvim marks ≠ vscode marks); requires user to learn a sase-specific
  convention inside their editor; doesn't compose with `kitten icat`-style image viewing for non-text files. We've
  already chosen Textual for the rest of the review surface — this would split the model.
- **When to pick**: only if we discover Option C's TUI cost is unacceptable.

### Option E — Sidecar review file (markdown driven)

`sase review start <file>` creates a structured markdown file (e.g.
`~/.sase/reviews/<ts>-<file>.review.md`) pre-populated with the file's content and one block per line where the user
can write notes. `sase review finalize` parses it back into the JSON.

- **Pros**: no TUI work; entire experience is "edit a markdown file"; trivially shareable.
- **Cons**: review file balloons in size; line-number drift if the source file changes; not interactive; harder to
  integrate with existing comment-display widgets.
- **When to pick**: probably not — Option A covers the "I just want to write comments in a file" use case more
  cleanly.

---

## Recommendation: Option C, with Option A as a thin co-feature

**Primary path**: TUI viewer + `c`-on-line + `$EDITOR` for body. This is the closest match to the existing mentor
review experience and the natural place a user would expect "review file" to live.

**Secondary path**: a thin `sase comment add <file>:<line> -m "..."` CLI for scripting / one-off cases. Same writer,
no new schema. Almost free once the writer exists.

**Reviewer name**: default to `"user"` (string literal). Add an opt-in config (`~/.config/sase/sase.yml`:
`user_comments.reviewer_name: bryan`) for users who want per-author reviewer names — but this is not v1.

**ChangeSpec coupling**: require an active ChangeSpec to register the COMMENTS drawer entry. If the user runs
`sase review <file>` outside a ChangeSpec, write the JSON to disk and print its path, but don't try to attach it
anywhere. (The mentor review modal won't see it, but the user can still `sase comments <path>` to render it.)

**Schema fit**: keep the strict mentor schema for v1 — it's good enough for "comment on a line." Defer ranges and
freeform tags to a v2 schema migration that mentor agents can also adopt.

**Apply pipeline**: do **not** auto-route user comments into the apply / commit pipeline. They're informational
unless the user explicitly invokes the existing "apply" action from the mentor review modal — which already operates
on any JSON in the right format.

---

## Risks & gotchas

- **Schema rigidity**: `severity` is a closed enum (`error|warning|suggestion`). User comments often want a 4th
  state ("nit", "question", "praise"). Either accept the constraint, extend the enum once and update all readers
  (`comments_handler.py`, `mentor_review_modal.py`, `_SEVERITY_STYLE`), or smuggle the user-facing tag into
  `focus_name`. Recommend extending the enum.
- **Line number drift**: comments reference `line_number` by integer. If the underlying file changes between comment
  authoring and review, the comment may point at the wrong line. Mentor comments have the same problem and accept it
  (review happens immediately after generation). For user comments authored over longer windows, consider snapshotting
  the file alongside (mentor already does this via `save_file_snapshots()` in `mentor_output.py:74-156` — reuse it).
- **Multiple comments on the same line**: schema permits this, but the existing TUI modal flattens by index. Verify
  it doesn't collapse them.
- **Keybinding collision**: `,c` in leader mode is currently `clear_comments` per `default_config.yml`. Don't reuse;
  pick a free slot like `,r` (review). Direct keys to avoid: `V` `E` `A` `-` `=` `d` `c` (in their respective modes).
- **`$EDITOR` suspension on tmux/SSH**: the suspend pattern works but can flicker; document expected behavior.
- **Validation race**: writing to `~/.sase/comments/...` then registering in `.gp` are two writes. Use the existing
  `changespec_lock()` (`src/sase/ace/changespec/`) so concurrent agents and the user don't corrupt the drawer.
- **Cross-platform paths**: comments JSON stores `file_path` strings — be explicit about whether they're absolute,
  repo-relative, or `~`-anchored. Mentor uses absolute paths today; match that.
- **Don't reinvent the rust core boundary**: per `memory/short/rust_core_backend_boundary.md`, the comment data model
  already exists in Rust as `CommentWire` (`sase-core/crates/sase_core/src/wire.rs:69-76`). The writer probably
  belongs on the Rust side with a thin Python adapter — confirm before implementation.

---

## Open questions for the user

1. **Entry surface**: confirm Option C (TUI viewer + `$EDITOR` body) is the right primary path, or push toward A
   (CLI-only, ship today) or D (no TUI viewer, lean on `$EDITOR`)?
2. **ChangeSpec coupling**: required, optional, or never? (Recommendation: optional — register if a ChangeSpec is
   active, otherwise just write the JSON.)
3. **Reviewer identity**: `"user"` literal for v1 OK?
4. **Schema extension**: are you OK extending `severity` (and updating mentor readers in lockstep), or should user
   comments squeeze into the existing 3 values?
5. **Line ranges**: needed in v1 ("lines 40-47"), or is single-line good enough?
6. **Apply integration**: should user comments be applyable via the existing mentor apply pipeline, or
   informational-only?
7. **Where does the writer live**: in the Rust core (`sase-core`) with a Python adapter, or Python-only for v1?

Answer these and the implementation plan writes itself from this doc.
