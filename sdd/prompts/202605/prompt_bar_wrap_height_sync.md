---
plan: sdd/tales/202605/prompt_bar_wrap_height_sync.md
---
 GitHub Actions is failing with the below error. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

```
=========================== short test summary info ============================
FAILED tests/ace/tui/widgets/test_prompt_virtual_wrap.py::test_initial_long_prompt_is_preserved_and_bar_grows_to_wrap - AssertionError: assert 8 == 9
 +  where 8 = _style_height_value(Scalar(value=8.0, unit=<Unit.CELLS: 1>, percent_unit=<Unit.WIDTH: 4>))
 +    where Scalar(value=8.0, unit=<Unit.CELLS: 1>, percent_unit=<Unit.WIDTH: 4>) = RenderStyles(PromptInputBar(), background=Color(0, 0, 0, a=0), height=Scalar(value=8.0, unit=<Unit.CELLS: 1>, percent_...to_link_color_hover=True, link_background_hover=Color(1, 120, 212), link_style_hover=Style(bold=True, underline=False)).height
 +      where RenderStyles(PromptInputBar(), background=Color(0, 0, 0, a=0), height=Scalar(value=8.0, unit=<Unit.CELLS: 1>, percent_...to_link_color_hover=True, link_background_hover=Color(1, 120, 212), link_style_hover=Style(bold=True, underline=False)) = PromptInputBar().styles
 +  and   9 = min((7 + 2), (16 - 2))
 +    where 7 = <textual.document._wrapped_document.WrappedDocument object at 0x7feea260ac50>.height
 +      where <textual.document._wrapped_document.WrappedDocument object at 0x7feea260ac50> = PromptTextArea(id='prompt-input').wrapped_document
 +    and   16 = Size(width=30, height=16).height
 +      where Size(width=30, height=16) = Screen(id='_default').size
 +        where Screen(id='_default') = _PromptBarApp(title='_PromptBarApp', classes={'-dark-mode'}, pseudo_classes={'dark', 'focus'}).screen
====== 1 failed, 7923 passed, 8 skipped, 47 warnings in 145.85s (0:02:25) ======
error: Recipe `test-cov` failed on line 139 with exit code 1
Error: Process completed with exit code 1.
```