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

### 7. `/sase_backup`: encrypted personal/Workspace account snapshots

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

## Recommended implementation order

1. **Calendar read-only skill**: small surface, immediately useful, low mutation risk.
2. **Drive/Docs read-only context skill**: high leverage for research and project context; needs careful artifact and
   untrusted-content handling.
3. **Workspace audit skill**: read-only reports into `sdd/research/YYYYMM/`; useful for both personal Drive cleanup and
   admin review.
4. **Tasks create-with-approval skill**: simple human-reviewed write path.
5. **Docs/Slides publishing skill**: powerful, but only after a clear "local artifact -> preview -> explicit write"
   workflow exists.
6. **Backup workflow documentation**: valuable, but keep it manual/scheduled rather than an ordinary agent skill.

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
- Local CLI inspection: `gog --help`, `gog schema --json`, and service-specific `gog <service> --help` on
  `gog v0.16.0-18-g9ebdc01`.
