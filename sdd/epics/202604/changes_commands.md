---
create_time: 2026-04-30 11:58:25
status: done
bead_id: sase-1k
prompt: sdd/prompts/202604/changes_commands.md
---
# ChangeSpec Copy Commands Plan

## Context

This work spans three repos:

- `sase_100` at `/home/bryan/projects/github/sase-org/sase_100`
- `sase-telegram` at `/home/bryan/projects/github/sase-org/sase-telegram`
- `retired chat plugin` at `/home/bryan/projects/github/sase-org/retired chat plugin`

The user-visible goal is:

- Telegram gets a new `/changes [project]` slash command.
- Google Chat gets a new `.changes [project]` dot command.
- Both commands list active ChangeSpecs only: exclude `Submitted`, `Archived`, and `Reverted` after normalizing status
  suffixes.
- Each listed ChangeSpec exposes the VCS xprompt workflow tag that should be copied, for example `#hg:foobar`.
- The optional argument is an exact project name filter. With no argument, list all active ChangeSpecs from all
  projects.

Existing code shape:

- ChangeSpecs are parsed by `sase.ace.changespec.find_all_changespecs()` and represented by
  `sase.ace.changespec.ChangeSpec`.
- Terminal statuses are defined by `sase.status_state_machine.constants.ARCHIVE_STATUSES`.
- Status values can carry suffixes; use `remove_workspace_suffix()` before comparing.
- The correct xprompt workflow prefix can be detected from a `.gp` file via
  `sase.workspace_provider.detect_workflow_type(project_file)`.
- Archive files may need normalization through `sase.ace.changespec.archive.get_main_file_path()` before workflow
  detection.
- Telegram already has slash-command registration and dispatch in `sase_telegram/scripts/sase_tg_inbound.py`, and
  `/resume` already uses Telegram `CopyTextButton` buttons.
- Google Chat dot commands are parsed in `retired_chat_plugin/inbound.py` and dispatched in
  `retired_chat_plugin/scripts/sase_gc_inbound.py`. Current gchat "copyable" UX is fenced code snippets, not true platform copy
  buttons, because `gchat_client.py` only wraps text messages, edits, uploads, reactions, and message reads.

Every phase below should be executed by a distinct agent instance. Each phase should begin by reading this plan and the
repo-specific files named in that phase. If a phase modifies `sase_100`, run `just install` if needed and then
`just check`. If a phase modifies a plugin repo, run `just install` if needed and then `just check` in that plugin repo.

## Cross-Phase Product Rules

- Tag text should be the bare workflow tag, with no trailing prompt text: `#hg:foobar`, `#gh:branch`, or `#git:branch`.
- The ref portion should be the ChangeSpec `NAME` exactly as stored, not the branch-derived hyphenated form.
- Filter by exact project name against `ChangeSpec.project_basename`. If a future repo has a parent directory name that
  differs from the file basename, exact matching against either value is acceptable, but do not introduce fuzzy
  matching.
- If multiple projects are shown, group or sort by project, then by ChangeSpec name. Keep output deterministic.
- If workflow detection fails for one or more active ChangeSpecs, do not crash the whole command. Show the entries whose
  tags can be produced and include a concise skipped-count note.
- Do not truncate the result set. If platform limits are a concern, split into multiple messages/chunks.

## Phase 1: Shared ChangeSpec Tag Listing Library

**Repo:** `sase_100`

**Primary files likely involved:**

- new module under `src/sase/`, for example `src/sase/integrations/changespec_tags.py`
- `tests/test_changespec_tags.py` or another focused test file
- possibly `src/sase/__init__.py` only if local conventions require exporting the helper

**Objective:** Create a single tested library API that both chat integrations can import.

**Suggested API:**

```python
@dataclass(frozen=True)
class ChangeSpecTagEntry:
    project: str
    name: str
    status: str
    workflow_type: str
    tag: str

@dataclass(frozen=True)
class ChangeSpecTagListing:
    entries: list[ChangeSpecTagEntry]
    skipped: list[str]

def list_changespec_xprompt_tags(project: str | None = None) -> ChangeSpecTagListing:
    ...
```

Implementation guidance:

- Load via `find_all_changespecs()`.
- Normalize status with `remove_workspace_suffix(cs.status)`.
- Exclude normalized statuses in `ARCHIVE_STATUSES`.
- Apply the optional project filter after parsing and before workflow detection to avoid unnecessary plugin calls.
- For workflow detection, use `cs.file_path`, but if it is an archive file, use the matching main file path.
- Build `tag = f"#{workflow_type}:{cs.name}"`.
- Return deterministic ordering by `(project, name, status)`.
- Keep the helper presentation-free: no Telegram imports, no Google Chat markdown, no HTML, no command parsing.

Tests:

- Includes WIP/Draft/Ready/Mailed entries.
- Excludes Submitted/Archived/Reverted, including statuses with suffixes that normalize to a terminal status.
- Filters by project.
- Detects workflow type per project and builds `#workflow:name`.
- Handles workflow detection failure by recording a skipped reason while still returning other entries.
- Keeps deterministic sorting.

Acceptance criteria:

- The helper is importable by external plugin repos when `sase` is installed.
- Unit tests pass in `sase_100`.
- `just check` passes in `sase_100`.

## Phase 2: Telegram `/changes [project]`

**Repo:** `../sase-telegram`

**Primary files likely involved:**

- `src/sase_telegram/scripts/sase_tg_inbound.py`
- `tests/test_inbound.py`
- `README.md`
- `docs/inbound.md`

**Objective:** Add the Telegram slash command using the Phase 1 helper.

Implementation guidance:

- Add `("changes", "Copy ChangeSpec workflow tags")` to `_SLASH_COMMANDS`.
- Add a `_handle_changes_command(args: str) -> None` branch in `_handle_command`.
- Parse zero or one argument. More than one argument should return a short usage message: `Usage: /changes [project]`.
- Call `list_changespec_xprompt_tags(project_arg_or_none)`.
- If no entries are returned:
  - no project: `No active ChangeSpecs.`
  - with project: `No active ChangeSpecs for <project>.`
- Render one inline copy button per entry:
  - button text should be short and scannable, for example `project/name` or `name` when filtered to one project.
  - button copy text is exactly `entry.tag`.
- Use `CopyTextButton`, matching the existing `/resume` style.
- Split into multiple Telegram messages if needed so all entries are shown. A conservative chunk size such as 40-60
  buttons per message is fine. Do not silently drop entries.
- Include a concise header such as `Active ChangeSpecs (N)` and a skipped-count note if Phase 1 reports skipped entries.
- Use existing escaping helpers and parse modes consistently with the surrounding command code.
- Delete or document `~/.sase/telegram/commands_registered_ts` in deployment notes so Telegram refreshes the registered
  command list without waiting up to an hour.

Tests:

- `_handle_command("/changes")` dispatches to the new handler.
- `_handle_command("/changes project")` passes the project filter.
- Unknown/multiple arguments return usage.
- No entries returns the correct empty message.
- Entries produce `InlineKeyboardButton` instances whose `copy_text.text` is the expected tag.
- A skipped entry note appears when the helper reports skipped items.
- Optional: chunking test for a result set larger than one message.

Acceptance criteria:

- `/changes` appears in Telegram command registration.
- `/changes` and `/changes <project>` both work manually.
- Result buttons copy tags like `#hg:foobar`.
- `just check` passes in `../sase-telegram`.

## Phase 3: Google Chat `.changes [project]`

**Repo:** `../retired chat plugin`

**Primary files likely involved:**

- `src/retired_chat_plugin/inbound.py`
- `src/retired_chat_plugin/scripts/sase_gc_inbound.py`
- `tests/test_inbound.py`
- `README.md`
- `docs/inbound.md`

**Objective:** Add the matching Google Chat dot command using the Phase 1 helper.

Implementation guidance:

- Add `changes` to `_DOT_COMMANDS`.
- Update `process_dot_command` docstrings and tests so `.changes` and `.changes project` parse as
  `DotCommand("changes", [...])`.
- Add an `_handle_dot_command` branch that calls `_format_changespec_tags(args: list[str]) -> str`.
- Parse zero or one argument. More than one argument should return `Usage: .changes [project]`.
- Call `list_changespec_xprompt_tags(project_arg_or_none)`.
- Since the current gchat wrapper does not support true copy buttons/cards, follow the repo's existing copyable-snippet
  convention used by `.kill` and `.resume`: render each tag in its own fenced block with a short description line.
- If an implementation agent confirms the local `gchat` CLI has a card/copy-button feature that is not yet wrapped, it
  may introduce a small wrapper and use real copy buttons, but that should stay scoped to this command and be covered by
  tests. Otherwise, do not expand transport scope just for visual parity.
- Split long result sets across multiple messages if the final text risks Google Chat message limits. If the existing
  command dispatcher only sends one string, either keep chunks modest enough or add a helper that sends multiple chunks
  for `.changes`; do not drop entries.
- Update `_HELP_TEXT` to include `.changes [project]`.

Tests:

- `process_dot_command(".changes")` and `process_dot_command(".changes myproj")` parse.
- `_handle_dot_command(DotCommand("changes", []), ...)` sends a response.
- Project filtering is passed through.
- Empty result and multiple-argument usage are covered.
- Output includes fenced `#hg:foobar` or equivalent tag snippets.
- Skipped entries produce a concise note.

Acceptance criteria:

- `.changes` and `.changes <project>` work in Google Chat.
- The output is copyable using the repo's established Google Chat convention, or true card copy buttons if the agent
  verifies and implements supported transport.
- `.help`, README, and inbound docs mention `.changes`.
- `just check` passes in `../retired chat plugin`.

## Phase 4: Cross-Repo Documentation and UX Consistency

**Repos:** `../sase-telegram`, `../retired chat plugin`, and only `sase_100` if Phase 1 docs need a follow-up.

**Objective:** Make the finished feature coherent across the two chat integrations.

Work:

- Compare Telegram and Google Chat output wording:
  - command names differ by platform (`/changes` vs `.changes`);
  - project filtering should be described identically;
  - status filtering should be described as "active ChangeSpecs" or "excluding Submitted, Archived, and Reverted".
- Update docs touched by Phases 2 and 3 if their wording diverged.
- Confirm Telegram registration includes `/changes`.
- Confirm Google Chat help includes `.changes`.
- Confirm both commands handle:
  - no active ChangeSpecs;
  - a matching project;
  - a non-matching project;
  - workflow detection failures;
  - a large enough list to require chunking or multiple messages.
- Run `just check` in both plugin repos and in `sase_100` if any main-repo code changed in this phase.

Acceptance criteria:

- A reviewer can read the docs and understand both commands without knowing implementation details.
- Both integrations produce the same tags for the same underlying ChangeSpecs.
- All modified repos pass their checks.

## Phase 5: Landing / Reviewer Handoff

**Repos:** all modified repos.

**Objective:** Final integration review and handoff after the distinct implementation agents finish.

Work:

- Review diffs across all repos for duplicated logic. The filtering and tag construction rules should live in the Phase
  1 helper, not separately in both chat integrations.
- Check that external repos import only public or stable `sase` APIs. If an internal import was necessary, record why in
  the final handoff.
- Verify no command accidentally launches an agent when the user typed `/changes` or `.changes`.
- Verify no command includes terminal ChangeSpecs.
- Run final checks:
  - `just check` in `sase_100`
  - `just check` in `../sase-telegram`
  - `just check` in `../retired chat plugin`
- Prepare the final implementation summary:
  - user-visible changes;
  - shared helper design;
  - tests run;
  - any platform limitation, especially if Google Chat uses fenced snippets instead of real copy buttons.

Acceptance criteria:

- The implementation is ready for review as a coherent multi-repo feature.
- Residual limitations are explicit and not hidden in code comments only.
