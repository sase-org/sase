---
plan: sdd/tales/202606/hint_bar_duplicate_id_crash.md
---
 Sometimes when I use the `v` (view) keymap the hints input bar loses focus for some reason. When this happens, if I press `v` again, `sase ace` crashes with an error like the (partial) one shown below. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
  
```
│ ╭─────────────────────────────────────────────────────────────────────────────────────────────── locals ────────────────────────────────────────────────────────────────────────────────────────────────╮ │
│ │   add_new_widget = <built-in method append of list object at 0x7f7528cc7980>                                                                                                                          │ │
│ │            after = None                                                                                                                                                                               │ │
│ │ apply_stylesheet = <bound method Stylesheet.apply of <Stylesheet [('/home/bryan/projects/github/sase-org/sase/src/sase/ace/tui/styles.tcss', ''),                                                     │ │
│ │                    ('/home/bryan/.local/share/uv/tools/sase/lib/python3.14/site-packages/textual/app.py', 'App.DEFAULT_CSS'),                                                                         │ │
│ │                    ('/home/bryan/.local/share/uv/tools/sase/lib/python3.14/site-packages/textual/screen.py', 'Screen.DEFAULT_CSS'),                                                                   │ │
│ │                    ('/home/bryan/.local/share/uv/tools/sase/lib/python3.14/site-packages/textual/widget.py', 'Widget.DEFAULT_CSS'),                                                                   │ │
│ │                    ('/home/bryan/.local/share/uv/tools/sase/lib/python3.14/site-packages/textual/widgets/_toast.py', 'ToastRack.DEFAULT_CSS'),                                                        │ │
│ │                    ('/home/bryan/.local/share/uv/tools/sase/lib/python3.14/site-packages/textual/widgets/_tooltip.py', 'Tooltip.DEFAULT_CSS'),                                                        │ │
│ │                    ('/home/bryan/.local/share/uv/tools/sase/lib/python3.14/site-packages/textual/widgets/_header.py', 'Header.DEFAULT_CSS'),                                                          │ │
│ │                    ('/home/bryan/.local/share/uv/tools/sase/lib/python3.14/site-packages/textual/containers.py', 'Horizontal.DEFAULT_CSS'),                                                           │ │
│ │                    ('/home/bryan/.local/share/uv/tools/sase/lib/python3.14/site-packages/textual/widgets/_header.py', 'HeaderIcon.DEFAULT_CSS'),                                                      │ │
│ │                    ('/home/bryan/.local/share/uv/tools/sase/lib/python3.14/site-packages/textual/widgets/_header.py', 'HeaderTitle.DEFAULT_CSS'),                                                     │ │
│ │                    ('/home/bryan/.local/share/uv/tools/sase/lib/python3.14/site-packages/textual/widgets/_static.py', 'Static.DEFAULT_CSS'),                                                          │ │
│ │                    ('/home/bryan/.local/share/uv/tools/sase/lib/python3.14/site-packages/textual/widgets/_header.py', 'HeaderClockSpace.DEFAULT_CSS'),                                                │ │
│ │                    ('/home/bryan/.local/share/uv/tools/sase/lib/python3.14/site-packages/textual/containers.py', 'Vertical.DEFAULT_CSS'),                                                             │ │
│ │                    ('/home/bryan/.local/share/uv/tools/sase/lib/python3.14/site-packages/textual/widgets/_option_list.py', 'OptionList.DEFAULT_CSS'),                                                 │ │
│ │                    ('/home/bryan/.local/share/uv/tools/sase/lib/python3.14/site-packages/textual/scroll_view.py', 'ScrollView.DEFAULT_CSS'),                                                          │ │
│ │                    ('/home/bryan/.local/share/uv/tools/sase/lib/python3.14/site-packages/textual/containers.py', 'ScrollableContainer.DEFAULT_CSS'),                                                  │ │
│ │                    ('/home/bryan/.local/share/uv/tools/sase/lib/python3.14/site-packages/textual/containers.py', 'VerticalScroll.DEFAULT_CSS'),                                                       │ │
│ │                    ('/home/bryan/.local/share/uv/tools/sase/lib/python3.14/site-packages/textual/widgets/_loading_indicator.py', 'LoadingIndicator.DEFAULT_CSS'),                                     │ │
│ │                    ('/home/bryan/.local/share/uv/tools/sase/lib/python3.14/site-packages/textual/widgets/_toast.py', 'ToastHolder.DEFAULT_CSS'),                                                      │ │
│ │                    ('/home/bryan/.local/share/uv/tools/sase/lib/python3.14/site-packages/textual/widgets/_toast.py', 'Toast.DEFAULT_CSS'),                                                            │ │
│ │                    ('/home/bryan/.local/share/uv/tools/sase/lib/python3.14/site-packages/textual/widgets/_input.py', 'Input.DEFAULT_CSS'),                                                            │ │
│ │                    ('/home/bryan/.local/share/uv/tools/sase/lib/python3.14/site-packages/textual/widgets/_text_area.py', 'TextArea.DEFAULT_CSS'),                                                     │ │
│ │                    ('/home/bryan/.local/share/uv/tools/sase/lib/python3.14/site-packages/textual/screen.py', 'ModalScreen.DEFAULT_CSS'),                                                              │ │
│ │                    ('/home/bryan/.local/share/uv/tools/sase/lib/python3.14/site-packages/textual/containers.py', 'Container.DEFAULT_CSS'),                                                            │ │
│ │                    ('/home/bryan/.local/share/uv/tools/sase/lib/python3.14/site-packages/textual/widgets/_label.py', 'Label.DEFAULT_CSS'),                                                            │ │
│ │                    ('/home/bryan/.local/share/uv/tools/sase/lib/python3.14/site-packages/textual/widgets/_button.py', 'Button.DEFAULT_CSS'),                                                          │ │
│ │                    ('/home/bryan/projects/github/sase-org/sase/src/sase/ace/tui/modals/user_question_modal.py', '_WrappingSelectionList.DEFAULT_CSS'),                                                │ │
│ │                    ('/home/bryan/.local/share/uv/tools/sase/lib/python3.14/site-packages/textual/widgets/_selection_list.py', 'SelectionList.DEFAULT_CSS')]>>                                         │ │
│ │           before = None                                                                                                                                                                               │ │
│ │            cache = {}                                                                                                                                                                                 │ │
│ │      new_widgets = [HintInputBar(id='hint-input-bar')]                                                                                                                                                │ │
│ │           parent = Vertical(id='agent-detail-container')                                                                                                                                              │ │
│ │             self = AceApp(title='sase ace (PID: 1638680)', classes={'-dark-mode', '-theme-flexoki'}, pseudo_classes={'focus', 'dark'})                                                                │ │
│ │           widget = HintInputBar(id='hint-input-bar')                                                                                                                                                  │ │
│ │      widget_list = (HintInputBar(id='hint-input-bar'),)                                                                                                                                               │ │
│ │          widgets = (HintInputBar(id='hint-input-bar'),)                                                                                                                                               │ │
│ ╰───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯ │
│                                                                                                                                                                                                           │
│ /home/bryan/.local/share/uv/tools/sase/lib/python3.14/site-packages/textual/app.py:3613 in _register_child                                                                                                │
│                                                                                                                                                                                                           │
│   3610 │   │   │   │   # At this point we appear to not be adding before or after,                                                                                                                        │
│   3611 │   │   │   │   # or we've got a before/after value that really means                                                                                                                              │
│   3612 │   │   │   │   # "please append". So...                                                                                                                                                           │
│ ❱ 3613 │   │   │   │   parent._nodes._append(child)                                                                                                                                                       │
│   3614 │   │   │                                                                                                                                                                                          │
│   3615 │   │   │   # Now that the widget is in the NodeList of its parent, sort out                                                                                                                       │
│   3616 │   │   │   # the rest of the admin.                                                                                                                                                               │
│                                                                                                                                                                                                           │
│ ╭─────────────────────────────────────────────────────────── locals ───────────────────────────────────────────────────────────╮                                                                          │
│ │  after = None                                                                                                                │                                                                          │
│ │ before = None                                                                                                                │                                                                          │
│ │  child = HintInputBar(id='hint-input-bar')                                                                                   │                                                                          │
│ │ parent = Vertical(id='agent-detail-container')                                                                               │                                                                          │
│ │   self = AceApp(title='sase ace (PID: 1638680)', classes={'-dark-mode', '-theme-flexoki'}, pseudo_classes={'focus', 'dark'}) │                                                                          │
│ ╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯                                                                          │
│                                                                                                                                                                                                           │
│ /home/bryan/.local/share/uv/tools/sase/lib/python3.14/site-packages/textual/_node_list.py:129 in _append                                                                                                  │
│                                                                                                                                                                                                           │
│   126 │   │   │   self._nodes_set.add(widget)                                                                                                                                                             │
│   127 │   │   │   widget_id = widget.id                                                                                                                                                                   │
│   128 │   │   │   if widget_id is not None:                                                                                                                                                               │
│ ❱ 129 │   │   │   │   self._ensure_unique_id(widget_id)                                                                                                                                                   │
│   130 │   │   │   │   self._nodes_by_id[widget_id] = widget                                                                                                                                               │
│   131 │   │   │   self.updated()                                                                                                                                                                          │
│   132                                                                                                                                                                                                     │
│                                                                                                                                                                                                           │
│ ╭────────────────────────────────────────────────────────────── locals ───────────────────────────────────────────────────────────────╮                                                                   │
│ │      self = <NodeList [AgentDetail(id='agent-detail-panel'), HintInputBar(id='hint-input-bar'), HintInputBar(id='hint-input-bar')]> │                                                                   │
│ │    widget = HintInputBar(id='hint-input-bar')                                                                                       │                                                                   │
│ │ widget_id = 'hint-input-bar'                                                                                                        │                                                                   │
│ ╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯                                                                   │
│                                                                                                                                                                                                           │
│ /home/bryan/.local/share/uv/tools/sase/lib/python3.14/site-packages/textual/_node_list.py:158 in _ensure_unique_id                                                                                        │
│                                                                                                                                                                                                           │
│   155 │   │   │   DuplicateIds: If the given ID is not unique.                                                                                                                                            │
│   156 │   │   """                                                                                                                                                                                         │
│   157 │   │   if widget_id in self._nodes_by_id:                                                                                                                                                          │
│ ❱ 158 │   │   │   raise DuplicateIds(                                                                                                                                                                     │
│   159 │   │   │   │   f"Tried to insert a widget with ID {widget_id!r}, but a widget already e                                                                                                            │
│   160 │   │   │   │   "ensure all child widgets have a unique ID."                                                                                                                                        │
│   161 │   │   │   )                                                                                                                                                                                       │
│                                                                                                                                                                                                           │
│ ╭────────────────────────────────────────────────────────────── locals ───────────────────────────────────────────────────────────────╮                                                                   │
│ │      self = <NodeList [AgentDetail(id='agent-detail-panel'), HintInputBar(id='hint-input-bar'), HintInputBar(id='hint-input-bar')]> │                                                                   │
│ │ widget_id = 'hint-input-bar'                                                                                                        │                                                                   │
│ ╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯                                                                   │
╰───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
DuplicateIds: Tried to insert a widget with ID 'hint-input-bar', but a widget already exists with that ID (HintInputBar(id='hint-input-bar')); ensure all child widgets have a unique ID.
```