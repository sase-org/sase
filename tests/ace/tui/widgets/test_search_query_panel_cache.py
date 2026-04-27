"""``SearchQueryPanel.render`` reads the app's saved-query cache, not disk."""

from __future__ import annotations

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.changespec_detail import SearchQueryPanel


class _Host(App):
    def __init__(self) -> None:
        super().__init__()
        self._saved_queries: dict[str, str] = {"1": "STATUS=Mailed"}

    def compose(self) -> ComposeResult:
        yield SearchQueryPanel(id="search-query-panel")


async def test_render_consults_app_cache_not_disk(monkeypatch) -> None:
    """``load_saved_queries`` must not be called from the hot render path."""
    calls = 0

    def _trip() -> dict[str, str]:
        nonlocal calls
        calls += 1
        return {}

    monkeypatch.setattr(
        "sase.ace.saved_queries.load_saved_queries",
        _trip,
    )

    app = _Host()
    async with app.run_test():
        panel = app.query_one(SearchQueryPanel)
        panel.update_query("STATUS=Mailed")
        # Force a render pass.
        text = panel.render()
        assert "Mailed" in text.plain

    assert calls == 0
