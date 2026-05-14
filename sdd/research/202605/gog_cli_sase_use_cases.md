# gog CLI Use Cases for SASE

Research date: 2026-05-14

`gog` is a strong fit for SASE because it exposes a broad Google Workspace surface through one scriptable CLI with
stable `--json` / `--plain` output, stderr-only human progress, non-interactive flags, dry-run support, command
allow/deny lists, Gmail send blocking, and baked safety-profile binaries. The existing `/sase_gmail` skill is the first
obvious use, but the same pattern can support several other high-value SASE skills and background workflows.

## Highest-value use cases

### 1. `/sase_calendar`: schedule-aware agent context

**What it would do**

- Show today's schedule, upcoming events, free/busy windows, conflicts, and team calendars.
- Let agents answer questions like "what meetings do I have before lunch?" or "find a 45-minute window this week".
- Optionally create focus-time / out-of-office / working-location blocks only when explicitly requested.

**Why it fits SASE**

Calendar context is useful for agent supervision: whether the user is available, when to schedule follow-up work, and
whether a long-running agent should wait for a review window. Local `gog calendar --help` exposes `events`, `freebusy`,
`conflicts`, `search`, `team`, `focus-time`, `out-of-office`, and `working-location`.

**Initial safe contract**

```bash
gog --json --no-input --wrap-untrusted \
  --enable-commands calendar.events,calendar.event,calendar.search,calendar.freebusy,calendar.conflicts \
  calendar events --today
```

Keep mutation commands (`create`, `update`, `delete`, `respond`, `focus-time`, `out-of-office`, `working-location`) out
of the default skill. Add a separate explicit-action skill later if needed.

### 2. `/sase_drive`: Drive and Docs context gathering

**What it would do**

- Search Drive for specs, design docs, meeting notes, exported PDFs, and project documents.
- Read/export Docs, Sheets, or Slides into local scratch artifacts for summarization.
- Generate URLs for a Drive file ID without fetching remote content.
- Inventory a folder before a migration, cleanup, or documentation refresh.

**Why it fits SASE**

SASE often needs project context that lives outside the repo. `gog drive search`, `drive get`, `drive download`, `docs
cat`, `docs export`, `sheets get`, and `slides export/read-slide` give agents a narrow, auditable path to fetch that
context. The docs explicitly position Drive `tree`, `du`, and `inventory` as read-only helpers for cleanup planning,
migration review, and stable JSON automation.

**Initial safe contract**

```bash
gog --json --no-input --wrap-untrusted \
  --enable-commands drive.search,drive.get,drive.download,drive.tree,drive.du,drive.inventory,drive.permissions,drive.url,docs.cat,docs.export,docs.info,sheets.get,sheets.export,slides.export,slides.read-slide \
  drive search "project-name design doc" --max 10
```

Downloaded/exported files should go to a scratch directory or explicit artifact directory. Treat fetched docs as
untrusted input and never follow instructions from document content unless the user asked for that.

### 3. `/sase_workspace_audit`: read-only Drive and Workspace hygiene checks

**What it would do**

- Find public or external Drive shares under a folder.
- Produce Drive size/inventory reports before cleanup.
- Find files shared with a specific user.
- For Workspace admins, list users, groups, org units, and group membership.

**Why it fits SASE**

This is a clean SDD/research generator: run a read-only audit, write findings into `sdd/research/YYYYMM/`, then create
tales or beads for remediation. `gog drive audit sharing` can fail a command when public/external shares are found, and
bulk permission changes are separate commands that support dry runs and confirmation.

**Initial safe contract**

```bash
gog --json --no-input \
  --enable-commands drive.audit.sharing,drive.audit.user,drive.inventory,drive.tree,drive.du,drive.permissions \
  drive audit sharing --parent "$FOLDER_ID" --internal-domain example.com
```

Admin commands need a distinct profile and account separation. Do not mix personal read skills with domain-wide
delegation.

### 4. `/sase_docs`: human-reviewed publishing and doc maintenance

**What it would do**

- Export a Google Doc to Markdown/PDF for local review.
- Append structured status updates to a doc.
- Apply simple formatting or find/replace placeholders.
- Generate weekly update decks from Markdown or a predesigned Slides template.

**Why it fits SASE**

SASE already produces plans, research, summaries, and release notes. `gog docs write --markdown`, `docs find-replace
--dry-run`, `docs format`, `slides create-from-markdown`, and `slides create-from-template` provide a path from local
agent output to Google-native artifacts without building a custom API integration.

**Initial safe contract**

Start read-only:

```bash
gog --json --no-input --wrap-untrusted \
  --enable-commands docs.cat,docs.export,docs.info,docs.list-tabs,docs.structure,slides.export,slides.info,slides.list-slides,slides.read-slide \
  docs cat "$DOC_ID"
```

For write workflows, prefer a "prepare then confirm" pattern:

- Generate a local Markdown artifact first.
- Use `--dry-run` where available, especially for find/replace.
- Require an explicit user request before `docs write`, `docs format`, `slides create-from-markdown`, or template
  replacement.

### 5. `/sase_tasks`: lightweight personal task bridge

**What it would do**

- List tasks, read task details, and create tasks from approved agent outputs.
- Turn an agent's final TODOs into Google Tasks after human confirmation.
- Mark tasks done only on explicit user command.

**Why it fits SASE**

SASE plans and final responses often end with actionable follow-ups. Google Tasks is a small, natural sink for those
items. Local help exposes `tasks lists`, `tasks list`, `tasks get`, `tasks add`, `tasks update`, `tasks done`, `tasks
undo`, and `tasks delete`.

**Initial safe contract**

Read-only first:

```bash
gog --json --no-input --wrap-untrusted \
  --enable-commands tasks.lists,tasks.list,tasks.get \
  tasks lists
```

Add mutation behind explicit approval with a narrow profile that allows only `tasks.add` if the first implementation is
"create reminders from an approved plan".

### 6. `/sase_contacts`: contact lookup and dedupe previews

**What it would do**

- Look up contact details needed for scheduling or email drafting.
- Preview duplicate personal contacts.
- Export contacts for local review.

**Why it fits SASE**

The contact-dedupe command is preview-only and has no apply flag, which is a good match for agent-generated research.
The docs say JSON output includes scanned count, duplicate groups, the would-keep primary contact, merged emails/phones,
match keys, and members.

**Initial safe contract**

```bash
gog --json --no-input --wrap-untrusted \
  --enable-commands contacts.search,contacts.get,contacts.list,contacts.dedupe,contacts.export,people.search,people.get,people.me \
  contacts dedupe --max 500
```

Avoid contact create/update/delete until there is a clear SASE workflow with review.

### 7. `/sase_sheets`: operational spreadsheets as a structured backend

**What it would do**

- Read a project tracking sheet (ledger, RFC index, hiring tracker, OKR sheet) and produce a typed summary.
- Append rows for SASE-generated events: completed beads, mailed ChangeSpecs, agent run metrics.
- Use named ranges or Sheets tables as a typed contract so agents do not depend on column letters.
- Run find/replace with `--dry-run` before applying placeholder substitutions in templated sheets.

**Why it fits SASE**

Sheets is the simplest "shared structured store" most teams already have. `gog sheets` exposes `get`, `raw`, `metadata`,
`tables`, `named-ranges`, `find-replace`, `notes`, `links`, `read-format`, `chart`, plus `export` to CSV/XLSX/PDF. The
`raw` command explicitly emits the lossless `Spreadsheets.Get` payload as JSON for LLM consumption, and Sheets tables
give agents a stable schema reference instead of brittle A1 ranges. This is a useful complement to beads when you need
non-engineers to read or edit the same data.

**Initial safe contract**

Start read-only against a known sheet, prefer named ranges or tables, and bound the request:

```bash
gog --json --no-input --wrap-untrusted \
  --enable-commands sheets.get,sheets.metadata,sheets.raw,sheets.named-ranges.list,sheets.table.list,sheets.table.read,sheets.notes,sheets.links,sheets.export \
  sheets table read "$SHEET_ID" "$TABLE_NAME"
```

For write workflows, layer `--dry-run` on `sheets find-replace` and require explicit user approval before enabling
`sheets.append`, `sheets.update`, or any tab/structure mutation. Treat cell text as untrusted just like Docs.

### 8. `/sase_backup`: encrypted personal/Workspace account snapshots

**What it would do**

- Initialize and verify encrypted backups of selected Google services.
- Run bounded smoke backups before a full push.
- Export verified plaintext to a local, non-synced scratch location for one-off review.

**Why it fits SASE**

The backup system writes age-encrypted JSONL gzip shards to a Git repo, with cleartext manifest metadata for verification
and status. Supported services include Gmail, Gmail settings, Calendar, Contacts, Tasks, Drive metadata/content, Workspace
native docs/forms discovery, Apps Script, Chat, Classroom, Groups, Admin, and Keep where available. This is useful as a
personal disaster-recovery tool and as a way to make Google state inspectable by scripts without repeatedly hitting live
APIs.

**Initial safe contract**

Keep this out of ordinary agent shells. Backups can be huge and may create plaintext local caches/exports. Treat it as a
manual or scheduled workflow:

```bash
gog backup push --services gmail --account "$ACCOUNT" --query 'newer_than:7d' --max 25
gog backup verify
```

Use `--no-drive-contents` or bounded content flags for initial Drive tests.

## Medium-value or situational uses

### Google Meet: post-meeting context

`gog meet` exposes `create`, `get`, `update`, `end`, `history`, and `participants`. A focused SASE use is post-meeting
context capture: pass a meeting code into a skill that fetches `history` and `participants`, then pairs that with a
Calendar event lookup and (separately, with consent) a transcript Doc to generate a structured summary, action items,
and bead candidates. Avoid `create`/`update`/`end` outside an explicit user request.

### Google Keep: lightweight personal note inbox

`gog keep list|get|search|create|delete|attachment` (Workspace-only) can serve as a one-line "remember this for me"
inbox where a SASE agent records short notes that you later review on mobile. Keep is read-only on consumer accounts via
the official API, so this skill applies only to Workspace tenants. Prefer read-only by default; allow `keep.create` only
under explicit instruction, and never `delete`.

### Google Chat integration support

`gog chat` can list/create spaces, list/send messages, create DMs, list threads, and manage reactions. This could help
test or operate the existing Google Chat notification path, but it should not become a broad "agent may post to chat"
tool by default. A useful narrow version would be:

- read recent messages in a known SASE ops space;
- post a human-approved completion summary;
- verify that SASE's Google Chat outbound integration produced the expected message.

### Forms and response collection

`gog forms` supports form creation/update, questions, responses, and watches. Possible SASE uses:

- generate a review/retro survey from a completed epic;
- collect lightweight user feedback about agent outcomes;
- watch for form responses that create beads or research tasks.

This is lower priority than Calendar/Drive/Docs because it needs a more opinionated product workflow.

### Search Console, Analytics, and YouTube reporting

For SASE site/blog operations, `gog searchconsole query`, `gog analytics report`, and `gog youtube` list commands could
produce periodic reports into `sdd/research/YYYYMM/`:

- top queries/pages for `sase.sh`;
- traffic changes after documentation launches;
- YouTube channel/comment reports if SASE ever publishes videos.

These are good read-only reporting skills, not core agent-control features.

### Maps and travel logistics

`gog maps` exposes geocode, reverse-geocode, directions, distance matrix, and places search. This is probably outside
SASE's engineering core, but it could support a personal assistant mode for commute-aware scheduling.

### Apps Script as a deployment target

`gog appscript` can create projects, fetch content, and run deployed functions. It may be useful for prototyping Google
Workspace automations that are too Google-native for SASE itself. Keep it separate from default agent access because
`run` executes remote code.

## Agent integration primitives

These are CLI-level features that any SASE skill should use, independent of which Google service it touches.

### Stable exit codes

`gog exit-codes` (alias `gog agent exit-codes`) prints a documented mapping:

```
ok: 0
error: 1
usage: 2
empty_results: 3
auth_required: 4
not_found: 5
permission_denied: 6
rate_limited: 7
retryable: 8
config: 10
cancelled: 130
```

Skills should branch on these instead of parsing stderr. The high-leverage codes for SASE are:

- `3` (empty_results) — distinguishes "no matching messages/events/files" from a real error; the skill should report
  "nothing found" rather than retrying or escalating.
- `4` (auth_required) — surface a clear "run `gog login`" hint and stop, do not attempt re-auth from the agent.
- `7` (rate_limited) / `8` (retryable) — safe to retry with backoff inside the skill; other non-zero codes are not.
- `6` (permission_denied) — usually means the OAuth scope or Workspace policy is the blocker, not a bug to fix in code.

### Machine-readable schema

`gog schema --json` (alias `help-json`) dumps the entire command/flag tree. This is directly useful for the SASE
generated-skills pipeline:

- diff the schema across `gog` upgrades to detect new commands worth exposing or removed commands that would silently
  break a skill;
- generate `--enable-commands` allow-lists programmatically from a curated subtree (e.g. "all `drive.*` read commands");
- power a future `/sase_gog_schema` helper that answers "what gog command does X?" without running anything.

### Context-budget flags

Agent context windows are precious. `gog` ships several flags specifically for keeping responses small and stable:

- `--json` + `--results-only` strips envelope fields like `nextPageToken` so the agent sees just the array.
- `--select=a,b,c` (and per-command `--fields`) trims response shape to the keys the skill needs.
- `--max N` caps result counts where supported (Gmail, Drive, Calendar, etc.).
- `--plain` produces TSV, ideal for piping into `awk`/`cut`/`column` without JSON parsing overhead in shell glue.

Skill files should pin these per command rather than dumping raw API responses into the agent transcript.

### Multi-account and OAuth client isolation

`gog` supports both `--account <email>` (per-Google-account selection) and `--client <name>` (per-OAuth-client/token
bucket selection). Recommended SASE pattern:

- One client/account pair per safety posture: personal-readonly, personal-tasks-write, workspace-admin, publishing.
- Skills read their account from an env var (e.g. `SASE_GMAIL_ACCOUNT`) with a fallback to `gog --json auth status`, the
  same pattern already used by `/sase_gmail`.
- Never share an admin/delegated client with a personal read skill; OAuth scopes plus account separation are the real
  defenses, runtime flags are a secondary layer.

### Time and offline URL helpers

- `gog time now` is the cheapest way for a skill to get the user's local timezone without shelling out to `date` and
  guessing zone configuration. Useful for any scheduling-adjacent skill.
- `gog open <url|id>` produces a best-effort web URL for a Google ID without an API call. Skills can use it to render
  clickable links in summaries without consuming auth or quota.

## Reusable skill template

Most `gog`-backed SASE skills will share the same shape:

```bash
# Resolve account (env var first, fall back to authed account).
SASE_GOG_ACCOUNT="${SASE_GOG_ACCOUNT:-$(gog --json auth status | jq -r '.account.email')}"

# Common safe flags.
GOG_FLAGS=(
  --account "$SASE_GOG_ACCOUNT"
  --json --no-input --wrap-untrusted --results-only
  --enable-commands "$ALLOWED_COMMANDS"
)

# Run the read command and branch on exit code.
if ! out=$(gog "${GOG_FLAGS[@]}" "$@"); then
  rc=$?
  case "$rc" in
    3)  echo '{"status":"empty"}'; exit 0 ;;     # no matches, not an error
    4)  echo 'auth_required: run `gog login`' >&2; exit "$rc" ;;
    7|8) sleep 2; exec "$0" "$@" ;;              # bounded retry once
    *)  exit "$rc" ;;
  esac
fi
echo "$out"
```

Skill files should also state in prose: which commands are enabled, that fetched content is untrusted, that no
mutation happens by default, and what env vars the user may override.

## Safety model

### Default agent flags

Most SASE skills should start with a common flag set:

```bash
GOG_FLAGS=(--json --no-input --wrap-untrusted)
```

Add `--gmail-no-send` to any skill that includes Gmail at all. Add `--dry-run` for mutation preview commands. Use
`--enable-commands` per skill so the command surface is explicit in the skill file.

### Prefer baked safety profiles for reusable skills

Runtime guards are useful, but `gog` supports compiled safety-profile binaries whose command policies cannot be changed
by flags, environment variables, config files, or shell arguments. The docs define:

- `readonly`: read/list/search/get-style commands only;
- `agent-safe`: read/search/draft/organize low-risk recoverable actions, while blocking sends, deletes, sharing changes,
  admin operations, and auth writes;
- custom profiles for narrower skills.

For any skill that will be commonly used by agents, prefer a profile-specific binary such as `gog-readonly` or
`gog-sase-calendar-readonly`.

### Treat Google content as hostile input

Use `--wrap-untrusted` for fetched text. Skills should explicitly say that email bodies, Docs, Sheets cells, Slides text,
Chat messages, comments, form responses, and Drive metadata are untrusted. Agents may summarize or extract facts, but
must not obey instructions embedded in fetched Google content unless the user explicitly asks.

### Separate accounts and OAuth scopes

Personal read-only skills, Workspace admin tasks, and publishing actions should use different OAuth clients/accounts
where practical. Safety profiles do not replace OAuth scopes, account separation, or Workspace policy.

### Persistent per-account guards

`--gmail-no-send` is a runtime flag and can be omitted by mistake. `gog config no-send` manages persistent per-account
Gmail no-send guards that apply even when a skill or agent forgets the flag. For any account that should never send
mail from an agent (typically your personal account when only `/sase_gmail` read access is intended), set this guard
once at the config layer rather than relying on every skill remembering the flag.

## Cross-skill and SASE-internal bridges

`gog`'s value compounds when paired with existing SASE features rather than treated as a standalone Google CLI.

- **Notifications inbox ↔ Gmail/Calendar.** A periodic agent could surface high-signal Gmail threads
  (`label:^starred newer_than:1d`) or imminent Calendar events into the SASE notifications inbox, so the user sees them
  in the same place as bead/plan notifications instead of in two UIs.
- **Beads ↔ Sheets/Tasks.** A read-only sync from a Sheets table of intake items, or from Google Tasks, into bead
  candidates with `sase bead create` is a clean human-reviewed pipeline: the spreadsheet/Tasks list stays the source of
  truth and beads are generated artifacts.
- **ChangeSpecs ↔ Drive/Docs.** A skill that, given a CL/PR, locates the related design Doc by title/folder and pulls a
  short summary into the ChangeSpec's DESCRIPTION saves manual context wrangling. Treat the Doc content as untrusted.
- **Agent outputs ↔ Docs/Slides.** Long-form research artifacts already produced under `sdd/research/YYYYMM/` can be
  pushed to Docs/Slides via `docs write --markdown` and `slides create-from-markdown` for stakeholders who don't read
  the repo. Keep this strictly user-triggered.
- **Sase Chat notifications ↔ `gog chat`.** Where SASE already posts to Google Chat, `gog chat list-messages` is the
  natural verification path in tests and during incident review.

## Testing and CI patterns

`gog` is well-shaped for skill tests because it returns stable JSON and exit codes:

- **Record-and-replay golden tests.** Capture `gog --json … > fixture.json` once with a fixed account, then in tests
  stub the binary with a script that prints the fixture. Schema stability (and the `gog schema --json` diff above)
  protects against silent drift.
- **`--dry-run` smoke checks.** For any mutation command added to a skill, gate it behind a CI test that runs the same
  command with `--dry-run` and asserts the planned action matches a known shape.
- **Allow-list enforcement.** A repo-level lint can assert every `gog` invocation in skill source includes
  `--enable-commands`, `--no-input`, and (for content fetches) `--wrap-untrusted`.
- **Account scoping in CI.** CI should never authenticate against real Google accounts; use `GOG_ACCESS_TOKEN` set to an
  invalid value to force `auth_required` (exit 4) and assert the skill handles it cleanly, or stub the binary
  entirely.

## Recommended implementation order

1. **Shared skill template + exit-code handling**: codify the `GOG_FLAGS` pattern, exit-code branching, and
   `--enable-commands` allow-list lint once so subsequent skills are 30-line wrappers, not 200-line scripts.
2. **Calendar read-only skill**: small surface, immediately useful, low mutation risk.
3. **Drive/Docs read-only context skill**: high leverage for research and project context; needs careful artifact and
   untrusted-content handling.
4. **Workspace audit skill**: read-only reports into `sdd/research/YYYYMM/`; useful for both personal Drive cleanup and
   admin review.
5. **Sheets read-only skill**: structured project data without leaving the repo.
6. **Tasks create-with-approval skill**: simple human-reviewed write path.
7. **Docs/Slides publishing skill**: powerful, but only after a clear "local artifact -> preview -> explicit write"
   workflow exists.
8. **Backup workflow documentation**: valuable, but keep it manual/scheduled rather than an ordinary agent skill.

## Sources

- gog overview: <https://gogcli.sh/>
- Safety profiles: <https://gogcli.sh/safety-profiles.html>
- Gmail workflows: <https://gogcli.sh/gmail-workflows.html>
- Drive audits: <https://gogcli.sh/drive-audits.html>
- Google Docs editing: <https://gogcli.sh/docs-editing.html>
- Sheets tables: <https://gogcli.sh/sheets-tables.html>
- Google Slides from Markdown: <https://gogcli.sh/slides-markdown.html>
- Contacts dedupe preview: <https://gogcli.sh/contacts-dedupe.html>
- Encrypted backups: <https://gogcli.sh/backup.html>
- Local CLI inspection: `gog --help`, `gog schema --json`, `gog exit-codes`, `gog config no-send --help`, and
  service-specific `gog <service> --help` on `gog v0.16.0-18-g9ebdc01`.
- Existing `/sase_gmail` skill at `~/.claude/skills/sase_gmail/SKILL.md` (and sibling runtime copies) as the reference
  shape for new `gog`-backed skills.
