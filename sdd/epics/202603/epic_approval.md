---
status: done
bead_id: sase-w0d2
prompt: sdd/prompts/202603/epic_approval.md
---

# Epic Plan Approval Support

Add an `E` (Epic) option to the TUI plan approval popup and a corresponding Telegram "Epic" inline keyboard button. When
used, instead of spawning a `.code` agent, spawn an `.epic` agent that runs
`#<vcs>:<name> #bd/new_epic:plans/<plan_name>.md`.

Also fix a related bug: the VCS xprompt (e.g. `#git:sase`) is NOT prepended to the `.code` agent's prompt.

## Phase 1: Foundation — bd xprompts in default_config.yml + beads detection helper

### Goal

Move bd xprompt definitions into sase core and add a helper to detect beads support.

### Changes

**`src/sase/default_config.yml`** — Add bd xprompts to the `xprompts:` section:

```yaml
xprompts:
  phase: |
    ...existing...
  bd/new_epic: |
    Can you help me create one bead for every phase in the @{1} plan file?

    These beads should all be children of a new epic bead (make sure this bead has a type of "epic" and not, for example,
    "feature") that you should also create. The epic bead should be linked to the plan file using the `tools/sase_bd create`
    command's `--design` option. Also, add the bead ID of the epic to a new frontmatter field called `bead_id` in the plan
    file.

    Make sure that each phase bead has the appropriate dependencies set up.
  bd/next: |
    ...content from ~/.local/share/chezmoi/home/dot_claude/commands/bd/next.md...
  bd/land_epic: |
    ...content from ~/.local/share/chezmoi/home/dot_claude/commands/bd/land_epic.md...
```

Note: Use legacy `{1}` placeholder syntax (not Jinja2) for the plan file argument in `bd/new_epic`, matching the `@$1`
pattern from the original Claude command. The other two (`bd/next`, `bd/land_epic`) may also have arguments that need
conversion from `$1` → `{1}` syntax.

**`src/sase/sdd.py`** — Add `has_beads_support()` helper:

```python
def has_beads_support(workspace_dir: str, workspace_num: int) -> bool:
    """Check if the project supports beads-based epic creation.

    True when both conditions hold:
    1. A .beads/ directory exists at the root of the primary workspace
    2. sdd.version_controlled is enabled in merged config
    """
    primary = Path(_get_primary_workspace_dir(workspace_dir, workspace_num))
    if not (primary / ".beads").is_dir():
        return False
    return get_sdd_config()
```

**`src/sase/notifications/senders.py`** — In `notify_plan_approval()`, add `beads_supported` and `workflow_name` to
`action_data` so TUI and Telegram can conditionally show the Epic option:

```python
def notify_plan_approval(
    ...,
    beads_supported: bool = False,
    workflow_name: str | None = None,
) -> None:
    ...
    if beads_supported:
        action_data["beads_supported"] = "1"
    if workflow_name:
        action_data["workflow_name"] = workflow_name
```

**`src/sase/llm_provider/_plan_utils.py`** — In `handle_plan_approval()`, pass new fields through to notification:

```python
def handle_plan_approval(
    ...,
    beads_supported: bool = False,
    workflow_name: str | None = None,
) -> str | None:
    ...
    notify_plan_approval(
        ...,
        beads_supported=beads_supported,
        workflow_name=workflow_name,
    )
```

### Tests

- Unit test `has_beads_support()` with mocked filesystem (beads dir exists/missing, config true/false).
- Verify bd xprompts are loadable via `get_all_xprompts()`.

---

## Phase 2: Core logic — epic action in plan approval + VCS xprompt bug fix

### Goal

Extend the plan approval flow to support an "epic" action alongside approve/reject, and fix the missing VCS xprompt in
the coder agent prompt.

### Changes

**`src/sase/llm_provider/_plan_utils.py`** — Change return type to include action:

```python
@dataclass
class PlanApprovalResult:
    """Result from plan approval flow."""
    action: str  # "approve", "epic", or "" (rejected/killed)
    plan_file: str | None = None

def handle_plan_approval(...) -> PlanApprovalResult:
    ...
    if response_data.get("action") == "approve":
        return PlanApprovalResult(action="approve", plan_file=plan_file)
    if response_data.get("action") == "epic":
        return PlanApprovalResult(action="epic", plan_file=plan_file)
    return PlanApprovalResult(action="")  # rejected
```

**`src/sase/axe_run_agent_runner.py`** — Three changes in the plan approval block (lines 279–335):

1. **Call `handle_plan_approval` with new args** (pass beads_supported and workflow_name):

   ```python
   from sase.sdd import has_beads_support
   beads_ok = has_beads_support(workspace_dir, workspace_num)

   result = handle_plan_approval(
       plan_data.get("plan_file"),
       str(uuid.uuid4()),
       killed_check=was_killed,
       beads_supported=beads_ok,
       workflow_name=workflow_name,
   )
   ```

2. **Handle the epic action** — after plan approval (after SDD file writing):

   ```python
   if result.action == "epic":
       # Epic: spawn .epic agent with bd/new_epic xprompt
       current_role_suffix = ".epic"
       current_artifacts_dir = create_followup_artifacts(
           project_name, agent_meta, current_role_suffix,
           convert_timestamp_to_artifacts_format(timestamp),
           workspace_num=workspace_num,
       )
       plan_name = os.path.splitext(os.path.basename(result.plan_file))[0]
       vcs_prefix = f"#{workflow_name}:{cl_name} " if workflow_name else ""
       current_prompt = f"{vcs_prefix}#bd/new_epic:plans/{plan_name}.md"
       continue
   ```

3. **Fix VCS xprompt bug for coder agent** — prepend VCS prefix to coder prompt:
   ```python
   # Plan approved -> spawn coder with plan as prompt
   current_role_suffix = ".code"
   ...
   vcs_prefix = f"#{workflow_name}:{cl_name} " if workflow_name else ""
   current_prompt = (
       f"{vcs_prefix}@{plan_data['plan_file']}\n\n"
       "The above plan has been reviewed and approved. "
       "Implement it now."
   )
   ```

### Update callers

The return type change in `handle_plan_approval` requires updating the call site in `axe_run_agent_runner.py`:

- Old: `approved = handle_plan_approval(...)` then `if not approved:`
- New: `approval = handle_plan_approval(...)` then check `approval.action`

### Tests

- Unit test the new `PlanApprovalResult` dataclass.
- Test that coder prompt includes VCS prefix.
- Test that epic prompt is constructed correctly.

---

## Phase 3: TUI — E keymap in plan approval modal

### Goal

Add a conditional `E` keymap to the plan approval modal, shown only when beads are available.

### Changes

**`src/sase/ace/tui/modals/plan_approval_modal.py`**:

1. Add `beads_supported` parameter to `__init__`:

   ```python
   def __init__(self, plan_file: str, *, beads_supported: bool = False) -> None:
       super().__init__()
       self._plan_file = plan_file
       self._feedback_mode = False
       self._beads_supported = beads_supported
   ```

2. Conditionally add `E` binding and hint in `compose()`:
   - Add to hints string: `[magenta]E[/magenta]=Epic` (only when `self._beads_supported`)
   - Note: Do NOT add `E` to the static `BINDINGS` list — instead, dynamically bind in `on_mount` or use Textual's
     `action_epic` + conditional check pattern.

3. Add `action_epic()`:

   ```python
   def action_epic(self) -> None:
       if self._feedback_mode or not self._beads_supported:
           return
       self.dismiss(PlanApprovalResult(action="epic"))
   ```

4. Handle the `E` key press in `on_key()` or add to BINDINGS: Since Textual BINDINGS are class-level, the simplest
   approach is to always include `("E", "epic", "Epic")` in BINDINGS but have `action_epic` no-op when
   `_beads_supported` is False. The hint text is dynamically composed anyway, so the key just won't be shown in the
   footer when beads aren't supported.

**`src/sase/ace/tui/actions/agents/_notification_actions.py`** — In `handle_plan_approval()`:

1. Extract `beads_supported` from notification action_data:

   ```python
   beads_supported = notification.action_data.get("beads_supported") == "1"
   ```

2. Pass to modal:

   ```python
   app.push_screen(
       PlanApprovalModal(plan_file, beads_supported=beads_supported),
       on_dismiss,
   )
   ```

3. Handle "epic" result in `on_dismiss` — write `{"action": "epic"}` to plan_response.json:
   ```python
   if result.action == "epic":
       response_data = {"action": "epic"}
   ```
   The existing code path for "approve" already writes response_data and dismisses the notification, so the epic path
   should mirror the approve path (write response, dismiss, set status override to "EPIC CREATED" or similar).

### Tests

- Verify modal shows `E` hint when beads_supported=True, hides it when False.
- Verify `action_epic` dismisses with correct result.

---

## Phase 4: Telegram — Epic inline keyboard button

### Goal

Add an "Epic" button to the Telegram plan approval inline keyboard, conditional on beads support.

### Changes

**`../sase-telegram/src/sase_telegram/formatting.py`** — In `_format_plan_approval()`:

Add the Epic button to the keyboard, conditional on `beads_supported` in action_data:

```python
beads_supported = n.action_data.get("beads_supported") == "1"
rows = [
    [
        InlineKeyboardButton("✅ Approve", callback_data=...),
        InlineKeyboardButton("❌ Reject", callback_data=...),
    ],
    [
        InlineKeyboardButton("💬 Feedback", callback_data=...),
    ],
]
if beads_supported:
    rows[1].append(
        InlineKeyboardButton(
            "📋 Epic",
            callback_data=callback_data.encode("plan", prefix, "epic"),
        ),
    )
keyboard = InlineKeyboardMarkup(rows)
```

**`../sase-telegram/src/sase_telegram/inbound.py`** — In `process_callback()`:

Add epic handling in the `cb.action_type == "plan"` block:

```python
elif cb.choice == "epic":
    return ResponseAction(
        action_type="plan",
        notif_id_prefix=cb.notif_id_prefix,
        response_path=response_path,
        response_data={"action": "epic"},
        answer_text="Epic created",
    )
```

### Tests

- Verify Epic button appears when `beads_supported` is in action_data.
- Verify Epic button is absent when `beads_supported` is not set.
- Verify callback handling returns correct response data for "epic" choice.

---

## Key Files Summary

| File                                                       | Phase | Change                                                   |
| ---------------------------------------------------------- | ----- | -------------------------------------------------------- |
| `src/sase/default_config.yml`                              | 1     | Add bd/new_epic, bd/next, bd/land_epic xprompts          |
| `src/sase/sdd.py`                                          | 1     | Add `has_beads_support()`                                |
| `src/sase/notifications/senders.py`                        | 1     | Add beads_supported + workflow_name to plan notification |
| `src/sase/llm_provider/_plan_utils.py`                     | 1,2   | Add params (P1), change return type (P2)                 |
| `src/sase/axe_run_agent_runner.py`                         | 2     | Handle epic action, fix VCS prefix bug                   |
| `src/sase/ace/tui/modals/plan_approval_modal.py`           | 3     | Add conditional E keymap                                 |
| `src/sase/ace/tui/actions/agents/_notification_actions.py` | 3     | Pass beads flag, handle epic result                      |
| `../sase-telegram/src/sase_telegram/formatting.py`         | 4     | Add conditional Epic button                              |
| `../sase-telegram/src/sase_telegram/inbound.py`            | 4     | Handle epic callback                                     |
