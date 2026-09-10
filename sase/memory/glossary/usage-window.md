---
keyword: Usage Window
aliases:
  - usage-window
---

A usage window is a provider-reported capacity allowance over a time interval, scoped to
all models or to a model/product subset, independently identified and measured, with a
reset time when the provider reports one. Claude examples include its five-hour
all-model window, weekly all-model window, and weekly Fable window.

Usage windows can overlap, and their percentages are independent: do not add, average,
or otherwise merge them. A window's duration is the size of the interval; time remaining
to reset is a separate clock-derived value.
