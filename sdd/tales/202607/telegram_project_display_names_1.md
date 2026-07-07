---
create_time: 2026-07-07 02:06:17
status: done
prompt: sdd/prompts/202607/telegram_project_display_names_1.md
---
# Fix Telegram surfaces showing canonical project directory keys instead of display names

## Problem

Telegram messages still show the canonical project directory key (e.g. `gh_sase-org__sase`, or its filename-sanitized
form `gh_sase_org__sase`) instead of the project display name (`sase`). Prior fixes (`1cbe79f91`, `b7e982967`,
`91d6a4f18`, `228fc78af`) covered the ACE TUI, but the `sase-telegram` plugin never got the same treatment.

Confirmed leak sites (from a live screenshot + a full audit of the `sase-telegram` repo):

1. **Prompt echoes in messages** — the workflow-complete "📝 Prompt:" block, the `/list` prompt snippet, the `/kill` and
   `/fork` selection descriptions, and the launch-notification prompt snippet all show `#gh:gh_sase-org__sase ...`
   verbatim.
2. **Copy-text buttons** — Fork/Wait buttons (workflow-complete message, launch notification, `/fork` command),
   Retry/Redo prompt buttons, and `/changes` ChangeSpec tag buttons all embed the canonical key
   (`#gh:gh_sase-org__sase`, `#gh:gh_sase-org__sase_<cl>`).
3. **Attachment filenames** — the response PDF is named after the chat file stem, e.g.
   `response-gh_sase_org__sase-ace_run-260707_011513-x35nwgg7.pdf`. Diff attachments (`<safe_cl_name>-<timestamp>.diff`)
   have the same problem when sent unembedded.

## Root cause

- The TUI display paths apply **both** `humanize_cl_names_in_text` (ChangeSpec/agent name tokens) and
  `humanize_vcs_refs_in_text` (project refs inside `#gh:`/`#git:`/... VCS workflow tags) — see
  `src/sase/ace/tui/modals/notification_modal_options.py` and `src/sase/ace/tui/agent_completion.py` in the `sase` repo.
- The Telegram plugin's `display_cl_names_in_text` (`src/sase_telegram/formatting.py`) only applies
  `humanize_cl_names_in_text`. The CL-name token regex cannot match a ref preceded by `:`, so `#gh:<project>` tags pass
  through untouched. Copy-text buttons use raw canonical tags directly, and attachment filenames are derived from raw
  chat-file stems with no humanization at all.
- Chat/diff filenames use `make_safe_filename(<key>)` (non-alphanumerics → `_`), so the on-disk prefix
  (`gh_sase_org__sase`) no longer literally matches the canonical key (`gh_sase-org__sase`); none of the existing
  humanizers can rewrite it.

## Why humanized copy-text is safe (round-trip)

Every launch boundary canonicalizes project refs in VCS workflow tags via `canonicalize_project_aliases_in_prompt`
(`src/sase/agent/launch_cwd_agents.py`, `launch_request.py`, `multi_prompt_launcher.py`, `launch_projects.py`, ...).
Telegram inbound prompts go through `launch_agents_from_cwd`, so a pasted `#gh:sase` or `#gh:sase_<cl-suffix>` resolves
back to the canonical key — `_rewrite_ref_with_known_prefix` handles both exact refs and `<display>_<suffix>` CL-name
refs in both directions. Verified live: `humanize_vcs_refs_in_text('#gh:gh_sase-org__sase ...')` → `'#gh:sase ...'`, and
the display map resolves `sase` back to `gh_sase-org__sase`.

**Deliberate non-goal:** `#fork:<agent_name>`, `%w:<agent_name>`, and `%n:<retry_name>` refs stay canonical. Agent-name
refs are _not_ project-alias-canonicalized at launch, so humanizing them would break resolution. The existing test
`test_humanizes_visible_text_but_keeps_fork_copy_raw` (sase-telegram `tests/test_formatting.py`) pins this and must keep
passing; it should be extended to also pin that the VCS-tag portion _is_ humanized. The "📋 Plan" copy button (a real
file path) also stays raw.

## Changes

### 1. `sase` repo — new display helper for sanitized filename stems

`src/sase/project_display_names.py`: add `humanize_safe_stem(stem: str, projects_root=None) -> str` (exported in
`__all__`):

- Build `make_safe_filename(canonical_key) -> display_name` from the existing mtime-cached display map
  (`_project_display_name_map_cached`).
- Longest-sanitized-key-first: if `stem` equals a sanitized key or starts with `<sanitized_key>-` or `<sanitized_key>_`,
  replace that prefix with the display name (which is already a valid filename token). Otherwise return the stem
  unchanged.
- This covers chat stems (`<safe_project>-<workflow>-<ts>`) and diff stems (`<safe_cl_name>-<ts>`, where the CL name
  itself starts with the project key + `_`).

Add unit tests in `tests/test_project_display_names.py` (exact match, `-`/`_` joined prefixes, hyphenated canonical key
sanitized to underscores, no-match passthrough, longest-key-first).

### 2. `sase-telegram` repo — formatting choke points

`src/sase_telegram/formatting.py`:

- Add `display_vcs_refs_in_text(text)`: lazy import of `sase.project_display_names. humanize_vcs_refs_in_text` with the
  same `ImportError`/`Exception` → identity fallback used by the existing `display_*` wrappers.
- Extend `display_cl_names_in_text` to apply `humanize_vcs_refs_in_text` **and** `humanize_cl_names_in_text` (mirrors
  the TUI's combined transform). This single change fixes all message-text leaks: `_format_notes_text`, the
  workflow-complete prompt echo, `/list` blocks, `/kill`/`/fork` descriptions, and launch-notification snippets — they
  already route through it.
- Add `display_safe_stem(stem)`: lazy wrapper around the new `humanize_safe_stem`.
- `_format_workflow_complete`: build the Fork button as `display_vcs_refs_in_text(vcs_tag) + f"#fork:{agent_name} "`
  (humanize after `replace_ref_in_vcs_tag`, keeping the agent-name ref raw).

### 3. `sase-telegram` repo — inbound copy-text sites

`src/sase_telegram/scripts/sase_tg_inbound.py`:

- Launch notification (~line 1888): humanize `vcs_prefix` via `display_vcs_refs_in_text` so the Fork and Wait copy-texts
  read `#gh:sase #fork:<name>` / `#gh:sase %w:<name>`.
- Retry button (~line 1896) and Redo button in `_send_kill_result`: run the built prompt through
  `display_vcs_refs_in_text` before the `_COPY_TEXT_MAX` check / `pending_actions` storage (the shorter humanized text
  also fits the 256-char copy limit more often).
- `/fork` command (~line 2339): humanize `vcs_prefix` the same way.
- `/changes` command (~line 2405): copy text becomes `display_vcs_refs_in_text(entry.tag)` (labels are already
  humanized).

### 4. `sase-telegram` repo — outbound attachment filenames

`src/sase_telegram/scripts/sase_tg_outbound.py`:

- `_make_response_only_file`: `original_name = display_safe_stem(Path(chat_path).stem)` so the response temp file — and
  the PDF derived from it — is named `response-sase-ace_run-<ts>-....pdf`.
- Extend `telegram_client.send_document` with an optional `filename: str | None = None` passthrough (python-telegram-bot
  ≥ 21 supports it) and, in the outbound attachment loop, pass a humanized display filename (`display_safe_stem` on the
  stem) for document sends whose stem changes under humanization (raw chat files, unembedded diffs). Media sends
  (photo/video) don't display filenames and need no change.

### 5. Tests (`sase-telegram` repo)

- `tests/test_formatting.py`: VCS tags humanized in prompt echo and notes; Fork copy-text shows humanized tag + raw
  agent ref (extend `test_humanizes_visible_text_but_keeps_fork_copy_raw`).
- `tests/test_inbound.py`: `/list` snippet, `/fork` and `/changes` copy-texts, retry/redo prompts.
- `tests/test_outbound.py`: response temp/PDF filename humanized; `send_document` filename override for diff
  attachments.
- Tests monkeypatch the `display_*` wrappers or the underlying `sase.project_display_names` functions, following
  existing patterns in these files.

## Verification

- `just check` in the `sase` repo; `just check` in the `sase-telegram` repo.
- Manual smoke test: trigger a workflow-complete notification for a `#gh:`-project agent and confirm (a) prompt echo
  shows `#gh:sase`, (b) Fork chip pastes `#gh:sase #fork:<name>` and a send of that text launches correctly
  (canonicalization at launch), (c) the response PDF is named `response-sase-...pdf`, (d) `/list` and `/changes` show no
  canonical keys.
