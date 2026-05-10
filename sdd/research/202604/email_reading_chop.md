# Email Reading for Sase Agents - Lumberjack Chop Research

**Date:** 2026-04-29  
**Goal:** Let sase agents read the user's email, starting with a lumberjack chop that surfaces new Gmail messages into
the existing sase notification system.  
**Recommendation:** Build a new `sase-gmail` plugin package with a `gm_inbound` script chop backed by the Gmail API,
then add a runtime-agnostic `sase-gmail` CLI as the follow-up path for in-flight agents that need to search/fetch mail.

## 1. Product Shape

"Agents can read email" can mean three different products. They should not be designed as one feature because they have
different trust boundaries and state models.

| Mode | User-facing behavior | Best mechanism | Risk level | v1? |
|---|---|---|---|---|
| **A. Email -> notifications** | New qualifying emails appear in ACE / telegram / gchat as ordinary sase notifications. | Periodic lumberjack script chop. | Low: read-only, no command execution. | **Yes** |
| **B. Email -> agent commands** | Email body launches an agent, answers a question, approves a plan, etc. | Inbound command chop plus allowlisted senders/labels. | High: turns email into an execution channel. | No |
| **C. Email-as-tool** | A running agent can search/fetch email on demand while doing a task. | `sase-gmail search|thread|show` CLI, returning JSON/text. | Medium: read access exposed to all runtimes. | Follow-up |

The user's "lumberjack chop" framing points to **Mode A**. Mode C is the more literal "agent reads email" feature, but
it should reuse the same Gmail auth/client code after Mode A proves the integration.

## 2. Existing Sase Patterns

Relevant local patterns checked:

- `src/sase/axe/chop_script_runner.py` discovers script chops as `sase_chop_<name>` in configured dirs, the current
  Python env's `bin/`, or `$PATH`.
- `src/sase/axe/lumberjack.py` passes `--context <ctx.json>`, runs eligible chops concurrently, and records
  `run_every` timestamps only after a successful exit.
- `src/sase/scripts/sase_chop_error_digest.py` is the minimal built-in script-chop reference.
- `retired chat plugin` and `sase-telegram` register chop executables with `[project.scripts]`, not with pluggy entry points.
- `retired chat plugin` stores channel state under `~/.sase/gchat/`, uses a lock file, bootstraps its high-water mark on first
  run to avoid backlog floods, and advances state only after successful delivery.
- `src/sase/notifications/senders.py` is the right place to add a typed sender helper, but arbitrary external tools can
  already append notification JSONL through the public store model.

Two corrections to the first draft:

1. A package does **not** need a custom `chop_script_dirs` entry if its console scripts are installed into the same
   environment or visible on `$PATH`; this is how `retired chat plugin` and `sase-telegram` work.
2. A notification with an unknown `action` is fine for display, but an email notification probably should use
   `action=None` in v1 unless we also add a concrete action handler. Put IDs in `action_data` for future use.

## 3. Package Placement

### Recommendation: new `sase-gmail` repo

Create a sibling plugin at `~/projects/github/sase-org/sase-gmail`, mirroring `retired chat plugin` and `sase-telegram`.

Why:

- Email has its own dependencies (`google-api-python-client`, `google-auth-oauthlib`, likely `google-auth-httplib2`).
- `retired Mercurial plugin` is currently Mercurial/external provider-focused; bundling Gmail there would make "Google" mean unrelated things.
- The existing comm-channel packages are standalone chop-script packages.
- A separate repo keeps auth docs, setup tests, and optional CLI commands isolated.

Minimal `pyproject.toml` shape:

```toml
[project]
name = "sase-gmail"
requires-python = ">=3.12"
dependencies = [
    "sase>=0.1.0",
    "google-api-python-client>=2",
    "google-auth-oauthlib>=1",
    "google-auth-httplib2>=0.2",
]

[project.scripts]
sase_chop_gm_inbound = "sase_gmail.scripts:inbound_main"
sase_gmail_setup = "sase_gmail.scripts:setup_main"
sase-gmail = "sase_gmail.cli:main"
```

If we want a first-class `sase gmail ...` command later, use a package script (`sase-gmail`) first unless core gets a
generic plugin hook for CLI subcommands.

## 4. Gmail API Transport

### Recommended v1 transport: Gmail API with installed-app OAuth

Use `google-api-python-client` and `google-auth-oauthlib`. Store the OAuth token under `~/.sase/gmail/token.json` with
mode `0600`; store the OAuth client configuration either under `~/.sase/gmail/client_secret.json` with mode `0600` or in
`pass`.

Start with `https://www.googleapis.com/auth/gmail.readonly`.

Important current facts from official docs:

- `gmail.readonly`, `gmail.modify`, `gmail.metadata`, and the broad `https://mail.google.com/` scope are **restricted**
  Gmail scopes. Restricted scope usage can require OAuth verification, and server-side storage/transmission of
  restricted data can trigger security assessment requirements.
- OAuth apps with external user type and publishing status `Testing` receive refresh tokens that expire after 7 days
  unless they only request basic profile/email/openid scopes.
- Gmail API quota is expressed in quota units with per-project and per-user-per-minute rate limits. `messages.list` and
  `messages.get` are 5 units each; `history.list` is 2 units.
- Gmail push notifications require Cloud Pub/Sub setup, `users.watch`, and watch renewal at least every 7 days. Push is
  not simpler than polling for a one-user local daemon.

Sources:

- Gmail API quota: https://developers.google.com/workspace/gmail/api/reference/quota
- Gmail push notifications: https://developers.google.com/workspace/gmail/api/guides/push
- Gmail scopes: https://developers.google.com/workspace/gmail/api/auth/scopes
- OAuth refresh-token expiration: https://developers.google.com/identity/protocols/oauth2#expiration

### Why not Pub/Sub push for v1?

Push looks attractive, but it adds Cloud Pub/Sub topic/subscription setup, IAM permissions for
`gmail-api-push@system.gserviceaccount.com`, notification acknowledgement, and a daily/weekly watch-renewal concern.
For a local sase daemon with a single mailbox, polling every 2-5 minutes is less moving machinery and easier to debug.

Keep push as a v2 option if polling latency or quota becomes a real issue.

### Why not IMAP?

IMAP keeps dependencies low, but Gmail API gives us better query syntax, labels, threads, message metadata formats, and
future mutation support. IMAP also pushes auth complexity into app passwords and Gmail account settings. It is a viable
fallback for non-Gmail mailboxes, not the best Gmail-native path.

### Why not the agent's Gmail MCP tools?

Any Gmail MCP tools available inside one model session are not a reliable interface for a lumberjack subprocess. A chop
runs as a normal executable, not as an MCP client inside the current agent runtime. The architecture should stay
runtime-agnostic per `memory/short/gotchas.md`; a CLI over the Gmail API works for Claude, Codex, Gemini, and future
runtimes.

Google does have Workspace developer MCP tooling, but current official docs describe it as a documentation/development
server, not as the production transport for a user's Gmail mailbox. Do not build the chop around MCP.

## 5. v1 Chop Design: `gm_inbound`

### Config

Add a dedicated lumberjack in user config. Keep it slower than telegram/gchat because email does not need 5-second
latency.

```yaml
axe:
  lumberjacks:
    gmail:
      interval: 30
      chop_timeout: "60s"
      chops:
        - name: gm_inbound
          description: "Surface new Gmail messages as sase notifications"
          run_every: 5m
          env:
            SASE_GMAIL_QUERY: "is:unread in:inbox -category:promotions -category:social"
            SASE_GMAIL_MAX_PER_TICK: "25"
            SASE_GMAIL_LOOKBACK_DAYS: "14"
```

`run_every: 5m` means the lumberjack wakes often but the chop runs only when due. The chop's own lock still matters
because manual `sase axe chop run gm_inbound` or overlapping processes can occur.

### State

Use `~/.sase/gmail/`:

| Path | Purpose |
|---|---|
| `token.json` | OAuth token/refresh token, mode `0600`. |
| `client_secret.json` | Optional local OAuth client secret, mode `0600`, if not using `pass`. |
| `state.json` | High-water state: latest `internalDate`, seen message IDs at that timestamp, optional `historyId`. |
| `delivered_ids.json` | Bounded recent message-ID cache for dedup across equal timestamps and query changes. |
| `inbound.lock` | `fcntl.flock` guard around one poll/deliver cycle. |
| `gmail_debug.log` | API errors, invalid JSON/token failures, retry exhaustion. |

Prefer `inbound.lock`, not `outbound.lock`; this chop is inbound from Gmail into sase.

`state.json` should be atomic-write JSON, not a raw timestamp file:

```json
{
  "version": 1,
  "latest_internal_date_ms": 1777400000000,
  "latest_message_ids": ["18f..."],
  "bootstrapped_at": "2026-04-29T10:30:00-04:00"
}
```

### Poll Algorithm

The first draft's simple `after:{last_seen}` approach has two gaps:

- Gmail search `after:` is date-granular in normal Gmail query syntax, not millisecond-granular.
- Multiple messages can share the same `internalDate`, so a single numeric HWM can drop or duplicate edge messages.

Use a bounded lookback query plus local dedup:

1. Acquire `inbound.lock`; if already held, exit 0.
2. If `state.json` is missing, bootstrap it to "now" and exit 0. Do not flood the inbox on first run.
3. Build query from `SASE_GMAIL_QUERY` plus `newer_than:${lookback_days}d` or a conservative `after:YYYY/MM/DD`.
4. Call `users.messages.list(userId="me", q=query, maxResults=max_per_tick)`.
5. Fetch each listed message with `users.messages.get(format="metadata", metadataHeaders=["From", "To", "Cc", "Subject", "Date", "Message-ID"])`.
6. Normalize fields into a small `EmailSummary`.
7. Sort ascending by `(internalDate, id)`.
8. Drop messages already below the HWM or present in `delivered_ids.json`.
9. For each remaining message, append one notification. After each successful append, atomically advance state and add
   the message ID to the delivered cache.
10. On API failure, log and exit non-zero so the lumberjack records an error and does not advance `run_every` timestamp.

This favors no-loss behavior over exact one-time delivery. The delivered-ID cache should be bounded, for example keep
the most recent 2,000 IDs or 30 days.

### Notification Shape

Add a helper in core `src/sase/notifications/senders.py`:

```python
def notify_email_received(
    subject: str,
    sender_email: str,
    sender_name: str | None,
    snippet: str,
    message_id: str,
    thread_id: str,
    internal_date_ms: int,
    labels: list[str],
    query: str,
) -> None:
    ...
```

Recommended notification:

```json
{
  "sender": "gmail",
  "notes": [
    "Email from Alice <alice@example.com>: Subject line",
    "Short Gmail snippet..."
  ],
  "files": [],
  "action": null,
  "action_data": {
    "provider": "gmail",
    "message_id": "...",
    "thread_id": "...",
    "internal_date_ms": "1777400000000",
    "query": "is:unread in:inbox ..."
  }
}
```

Do not include full email bodies in notifications by default. Full body text belongs in Mode C commands or in an
explicit action such as `OpenEmailThread` later. This keeps `notifications.jsonl` from becoming a long-term mail body
cache.

### Formatting

v1 can rely on generic ACE / telegram / gchat rendering. It will be readable if the `notes` are concise.

Optional follow-up polish:

- Add gmail-specific formatter branches in `retired chat plugin` and `sase-telegram`.
- Add an ACE action handler to open a local text export or run `sase-gmail show --message-id ...`.
- Add muted defaults for noisy labels/senders.

## 6. Auth Setup

Add a setup script, likely `sase_gmail_setup`, with this flow:

1. Validate `~/.sase/gmail` exists with `0700`.
2. Locate OAuth client config:
   - `SASE_GMAIL_CLIENT_SECRET_JSON` path, or
   - `pass show sase/gmail/client_secret.json`, or
   - `~/.sase/gmail/client_secret.json`.
3. Run `InstalledAppFlow.from_client_secrets_file(..., scopes=[gmail.readonly]).run_local_server()`.
4. Write `token.json` with `0600`.
5. Make one `users.getProfile(userId="me")` call and print the authenticated email address.
6. Print the effective query and a dry-run count for `gm_inbound`.

Docs must be explicit that a personal/unverified OAuth app in `Testing` status will need re-authentication after 7 days.
For the user's own local app, possible paths are:

- Make the OAuth app internal if the account is in a Workspace org that allows it.
- Publish the OAuth app and keep it private to the user where possible.
- Accept 7-day reauth during development.

Because Gmail read scopes are restricted, avoid implying this can become a widely distributed public app without
verification work.

## 7. Mode C Follow-Up: Agent Email CLI

After the chop works, add a CLI that uses the same `gmail_client.py` and token store:

```bash
sase-gmail search -q 'from:alice newer_than:30d' --limit 10 --json
sase-gmail show --message-id 18fabc... --format text
sase-gmail thread --thread-id 18fabd... --format markdown
```

Output rules:

- Default to metadata/snippet for search.
- Require an explicit `show`/`thread` call to fetch bodies.
- Return JSON by default for agents, with `--format text|markdown|json` for humans.
- Strip or summarize attachments unless `--include-attachments` is explicitly requested.
- Never mutate read/unread state in the read-only CLI.

This is the runtime-agnostic path that actually lets agents read email during a task.

## 8. Mode B: Email as Command Channel

Defer this. If built later, require all of:

- Dedicated Gmail label, for example `sase-command`.
- Sender allowlist.
- Subject/body marker, for example `[sase]`.
- No implicit plan approval or command execution from arbitrary mail.
- Pending-action style confirmation for any destructive operation.
- Full audit notification for every accepted/rejected command email.

Email is a poor trust boundary. Mode B should be treated more like a privileged remote-control channel than like a
notification source.

## 9. Error Handling and Backoff

`gmail_client.py` should centralize retries and debug logging.

Retry:

- 429 / 403 rate-limit variants: exponential backoff with jitter, then fail the chop if exhausted.
- 500 / 502 / 503 / 504: retry.
- Auth errors (`invalid_grant`, revoked token): fail fast with a clear stderr line pointing to `sase_gmail_setup`.
- Invalid query: fail fast and log the query.

Do not advance state on any failed API call before notification append. Advance per delivered message, as gchat does,
so a partial tick only reprocesses the undelivered tail.

## 10. Privacy Defaults

The default should avoid quietly copying the user's mailbox into SASE artifact files.

Recommended defaults:

- Store metadata/snippet only in notifications.
- Do not store full body by default.
- Do not download attachments in v1.
- Redact or truncate snippets above a small limit, for example 300 chars.
- Keep delivered-ID cache bounded.
- Put all tokens/secrets under `~/.sase/gmail` with strict permissions.
- Consider `SASE_GMAIL_NOTIFY_MUTED=1` or sender/label deny lists for noisy sources.

If Mode C stores fetched bodies for debugging, use a separate cache with an expiry policy and make it opt-in.

## 11. Test Plan

Core repo (`sase_100`):

- Unit test `notify_email_received` creates a `Notification` with expected sender, notes, and action data.
- Confirm `action=None` notifications render in ACE's generic modal path.

`sase-gmail` repo:

- `gmail_client.py`: mock Gmail service for list/get, retryable errors, invalid query, auth failure.
- State management: first-run bootstrap, equal-`internalDate` dedup, bounded delivered-ID cache, atomic writes.
- Chop script: lock held -> exits 0; dry-run prints candidates but does not append or advance; partial append advances
  only delivered messages.
- Setup script: writes `0600` token file and fails clearly when client secret is missing.
- Integration smoke test using a fake service object, not live Gmail.

Manual verification:

```bash
just install
sase_gmail_setup
sase axe chop list | rg gm_inbound
sase axe chop run gm_inbound
tail -n 5 ~/.sase/notifications/notifications.jsonl
```

## 12. Implementation Plan

1. Create `sase-gmail` skeleton mirroring `retired chat plugin`: `pyproject.toml`, `Justfile`, `README.md`, `src/sase_gmail/`,
   `tests/`.
2. Implement local state helpers: permissions, atomic JSON write, lock, delivered-ID cache.
3. Implement `gmail_client.py` with OAuth token loading, service construction, `list_message_ids`, `get_message_summary`,
   retry/debug logging.
4. Implement `sase_chop_gm_inbound.py` with `--context` and `--dry-run`.
5. Add `notify_email_received` to `sase_100/src/sase/notifications/senders.py`.
6. Add focused tests in both repos.
7. Add user config stanza in chezmoi `sase_athena.yml` after manual dry-run succeeds.
8. Follow up with `sase-gmail search/show/thread` CLI for Mode C.

## 13. Open Questions

- Should the default query be `is:unread in:inbox` or just `in:inbox`? `is:unread` is less noisy but can miss messages
  the user read on phone before the chop runs.
- Should the chop mark messages as read or label them after notification? v1 should not; doing so requires
  `gmail.modify`, a broader restricted scope.
- Should email notifications be muted by default in ACE and only forwarded to telegram/gchat when idle? Existing
  notification semantics can support this, but it needs a product decision.
- Should `sase-gmail` expose a core `sase gmail` subcommand eventually? Today the easiest route is a package-level
  `sase-gmail` executable.

## Appendix: File References

- `src/sase/axe/lumberjack.py` - run loop, `run_every`, concurrent chop execution.
- `src/sase/axe/chop_script_runner.py` - script discovery and `--context` invocation.
- `src/sase/axe/chop_script_context.py` - context schema passed to script chops.
- `src/sase/scripts/sase_chop_error_digest.py` - minimal built-in script chop.
- `src/sase/notifications/senders.py` - typed notification sender helpers.
- `src/sase/notifications/models.py` and `src/sase/notifications/store.py` - JSONL notification model/storage.
- `~/projects/github/sase-org/retired chat plugin/src/retired_chat_plugin/scripts/sase_gc_outbound.py` - modern chop entry point.
- `~/projects/github/sase-org/retired chat plugin/src/retired_chat_plugin/outbound.py` - high-water mark and lock pattern.
- `~/projects/github/sase-org/retired chat plugin/src/retired_chat_plugin/gchat_client.py` - retry/debug-log wrapper pattern.
- `~/projects/github/sase-org/sase-telegram/src/sase_telegram/credentials.py` - `pass`-backed secret pattern.
- `~/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml` - user lumberjack config target.
