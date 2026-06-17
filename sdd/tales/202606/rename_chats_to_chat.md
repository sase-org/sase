---
create_time: 2026-06-17 07:11:19
status: done
prompt: sdd/prompts/202606/rename_chats_to_chat.md
---
# Rename `sase chats` to `sase chat`

## Goal

Make `sase chat` the canonical CLI command for discovering and inspecting saved agent chat transcripts. The existing
subcommands stay the same:

```bash
sase chat list
sase chat show
```

The generated slash skill name remains `/sase_chats`; only the CLI command it documents changes. I will not keep a
visible `sase chats` alias unless review requests backward compatibility, because the request is a rename and keeping
the old command would let stale references survive.

## Context Found

- The command is currently registered in `src/sase/main/parser_chats.py`, dispatched from `src/sase/main/entry.py`, and
  handled through `src/sase/main/chats_handler.py`.
- The concrete list/show implementations live under `src/sase/chats/`.
- Current user-facing command references appear in docs, CLI/help tests, `src/sase/history/chat_catalog.py`, and bundled
  skill sources under `src/sase/xprompts/skills/`.
- `memory/long/generated_skills.md` says generated provider `SKILL.md` files are produced from
  `src/sase/xprompts/skills/`; therefore the source skill files must be edited, then provider skills regenerated.
- Current repo docs and parser tests show the supported generation command is `sase skill init --force`
  (`sase init skills` is the compatibility alias; legacy top-level `sase init-skills` is rejected).
- There are historical SDD prompts, tales, bead records, and event streams that mention `sase chats`. I will audit those
  separately after live-code/docs updates and avoid rewriting immutable historical records unless they are active
  user-facing documentation.

## Implementation Plan

1. Rename the public CLI surface.
   - Register the top-level parser as `chat`.
   - Dispatch `args.command == "chat"` in `src/sase/main/entry.py`.
   - Update usage text, docstrings, comments, and stderr prefixes from `sase chats ...` to `sase chat ...`.
   - Prefer renaming focused internal CLI modules/functions from `chats` to `chat` where that removes stale command
     naming without touching the persistent `~/.sase/chats/` storage model.

2. Keep transcript storage semantics unchanged.
   - Do not rename `~/.sase/chats/`.
   - Do not rename generic domain objects such as chat transcript helpers or the `/sase_chats` skill name.
   - Keep JSON output shape and `list`/`show` behavior unchanged.

3. Update current references.
   - Update `src/sase/xprompts/skills/sase_chats.md` command examples to `sase chat`.
   - Update cross-skill guidance in `src/sase/xprompts/skills/sase_agents_status.md`.
   - Update docs in `docs/cli.md`, `docs/configuration.md`, and `docs/xprompt.md`.
   - Update source docstrings/comments in transcript catalog code that describe the CLI contract.
   - Update tests and expected phrases so they pin `sase chat`.

4. Regenerate generated skill output.
   - Run `sase skill init --force` after changing bundled skill sources.
   - If chezmoi deployment is enabled, allow that command to deploy/apply through its normal repo logic rather than
     hand-editing generated `SKILL.md` files.

5. Sweep for stale references.
   - Run exact-string searches over live code, tests, docs, config, and root markdown for:
     - `sase chats`
     - `parser_chats`, `chats_handler`, `chats_subcommand`, `args.command == "chats"`
     - `sase.chats`
   - Run a separate SDD sweep for `sase chats` and classify remaining matches as either active documentation to update
     or archival history to leave unchanged and report.

6. Validate behavior.
   - Run the focused tests for chat CLI parsing/handling, root parser default-list behavior, and generated skill source
     discovery.
   - Run `sase chat --help`, `sase chat list --help`, and `sase chat show --help` to verify the public help is clear.
   - Run `sase chat list -j -l 1` as a smoke test.
   - Run `just install` if needed for the ephemeral workspace, then `just check` because this will change repo files.

## Risks And Checks

- The main compatibility choice is whether to keep a hidden `sase chats` alias. My default is no alias, because the
  request is to rename the command and update all references.
- The persistent directory name `chats` is intentionally not part of the rename; changing it would be a data migration
  and is out of scope.
- Historical SDD/bead/event files may retain old command text for audit accuracy. I will make any such leftovers
  explicit rather than allowing them to look accidental.
