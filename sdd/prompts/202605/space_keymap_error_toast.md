---
plan: sdd/tales/202605/space_keymap_error_toast.md
---
 The following crash occurred when I used the `<space>` keymap in the TUI. Can you help me make it so this doesn't cause a crash, but instead just shows an error toast in the TUI? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

```
❯ sase ace
╭───────────────────────────────────────────────────────────────────────────────────────── Traceback (most recent call last) ──────────────────────────────────────────────────────────────────────────────────────────╮
│ /home/bryan/projects/github/sase-org/sase/src/sase/ace/tui/actions/agent_workflow/_entry_points.py:68 in action_start_agent_from_changespec                                                                          │
│                                                                                                                                                                                                                      │
│    65 │   │   if last is None:                                                                 ╭────────────────────────────────────────────────── locals ───────────────────────────────────────────────────╮       │
│    66 │   │   │   self.notify("No previous @/<space> selection", severity="warning")  # type:  │ last = SelectionItem(display_name='branch', item_type='cl', project_name='project', cl_name='branch')       │       │
│    67 │   │   │   return                                                                       │ self = AceApp(title='sase ace', classes={'-dark-mode', '-theme-flexoki'}, pseudo_classes={'dark', 'focus'}) │       │
│ ❱  68 │   │   self._start_custom_agent_from_selection(last)                                    ╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────╯       │
│    69 │                                                                                                                                                                                                              │
│    70 │   def _start_prompt_history_from_last_selection(                                                                                                                                                             │
│    71 │   │   self, *, show_cancelled: bool = False                                                                                                                                                                  │
│                                                                                                                                                                                                                      │
│ /home/bryan/projects/github/sase-org/sase/src/sase/ace/tui/actions/agent_workflow/_entry_points.py:291 in _start_custom_agent_from_selection                                                                         │
│                                                                                                                                                                                                                      │
│   288 │   │   )                                                                                                                                                                                                      │
│   289 │   │                                                                                                                                                                                                          │
│   290 │   │   if selection.item_type == "cl" and selection.cl_name:                                                                                                                                                  │
│ ❱ 291 │   │   │   prefix = _vcs_prompt_prefix(project_file, selection.cl_name)                                                                                                                                       │
│   292 │   │   │   if open_in_editor:                                                                                                                                                                                 │
│   293 │   │   │   │   self._select_and_open_editor_for_home(  # type: ignore[attr-defined]                                                                                                                           │
│   294 │   │   │   │   │   initial_text=prefix,                                                                                                                                                                       │
│                                                                                                                                                                                                                      │
│ ╭─────────────────────────────────────────────────────── locals ────────────────────────────────────────────────────────╮                                                                                            │
│ │ open_in_editor = False                                                                                                │                                                                                            │
│ │   project_file = '/home/bryan/.sase/projects/project/project.gp'                                                      │                                                                                            │
│ │   project_name = 'project'                                                                                            │                                                                                            │
│ │      selection = SelectionItem(display_name='branch', item_type='cl', project_name='project', cl_name='branch')       │                                                                                            │
│ │           self = AceApp(title='sase ace', classes={'-dark-mode', '-theme-flexoki'}, pseudo_classes={'dark', 'focus'}) │                                                                                            │
│ ╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯                                                                                            │
│                                                                                                                                                                                                                      │
│ /home/bryan/projects/github/sase-org/sase/src/sase/ace/tui/actions/agent_workflow/_entry_points.py:28 in _vcs_prompt_prefix                                                                                          │
│                                                                                                                                                                                                                      │
│    25 │   """                                                                                  ╭──────────────────────────── locals ────────────────────────────╮                                                    │
│    26 │   from sase.workspace_provider import detect_workflow_type                             │         name = 'branch'                                        │                                                    │
│    27 │                                                                                        │ project_file = '/home/bryan/.sase/projects/project/project.gp' │                                                    │
│ ❱  28 │   workflow_type = detect_workflow_type(project_file)                                   ╰────────────────────────────────────────────────────────────────╯                                                    │
│    29 │   return f"#{workflow_type}:{name} "                                                                                                                                                                         │
│    30                                                                                                                                                                                                                │
│    31                                                                                                                                                                                                                │
│                                                                                                                                                                                                                      │
│ /home/bryan/projects/github/sase-org/sase/src/sase/workspace_provider/_registry.py:117 in detect_workflow_type                                                                                                       │
│                                                                                                                                                                                                                      │
│   114 │   result = _get_manager().detect_workflow_type(project_file)                           ╭──────────────────────────── locals ────────────────────────────╮                                                    │
│   115 │   if result is not None:                                                               │ project_file = '/home/bryan/.sase/projects/project/project.gp' │                                                    │
│   116 │   │   return result                                                                    │       result = None                                            │                                                    │
│ ❱ 117 │   raise ValueError(                                                                    ╰────────────────────────────────────────────────────────────────╯                                                    │
│   118 │   │   f"No workspace plugin detected a workflow type for '{project_file}'. "                                                                                                                                 │
│   119 │   │   f"Install the appropriate workspace plugin."                                                                                                                                                           │
│   120 │   )                                                                                                                                                                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
ValueError: No workspace plugin detected a workflow type for '/home/bryan/.sase/projects/project/project.gp'. Install the appropriate workspace plugin.
```

### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md (memory/long/external_repos, matched: `plugin`)