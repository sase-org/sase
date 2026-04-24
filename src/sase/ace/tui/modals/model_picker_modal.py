"""Model picker modal for selecting a coder LLM model."""

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets._option_list import Option

from .base import OptionListNavigationMixin

# Sentinel returned when user selects "Custom..."
CUSTOM_SENTINEL = "__custom__"


def _build_model_options() -> list[Option | None]:
    """Build the option list items grouped by provider."""
    from sase.llm_provider.registry import model_to_provider_map

    # Group models by provider, preserving insertion order
    provider_models: dict[str, list[str]] = {}
    for model, provider in model_to_provider_map().items():
        provider_models.setdefault(provider, []).append(model)

    items: list[Option | None] = [
        Option("Same as planner", id="__default__"),
    ]

    for provider, models in provider_models.items():
        items.append(None)  # separator
        items.append(
            Option(f"  {provider.upper()}", id=f"__header_{provider}__", disabled=True)
        )
        for model in models:
            items.append(Option(f"    {model}", id=model))

    items.append(None)  # separator
    items.append(Option("  Custom...", id=CUSTOM_SENTINEL))

    return items


class ModelPickerModal(OptionListNavigationMixin, ModalScreen[str | None]):
    """Modal for selecting a coder LLM model."""

    _option_list_id = "model-picker-list"

    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        ("enter", "select_model", "Select"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="model-picker-container"):
            yield Static(
                "[bold cyan]Select Coder Model[/bold cyan]",
                id="model-picker-title",
            )
            yield OptionList(
                *_build_model_options(),
                id="model-picker-list",
            )
            yield Static(
                "[green]enter[/green]=Select  "
                "[dim]j/k[/dim]=Navigate  "
                "[dim]q/esc[/dim]=Cancel",
                id="model-picker-footer",
            )

    def on_mount(self) -> None:
        self.query_one("#model-picker-list", OptionList).focus()

    def action_select_model(self) -> None:
        option_list = self.query_one("#model-picker-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return
        option = option_list.get_option_at_index(highlighted)
        option_id = str(option.id)
        if option_id == "__default__":
            self.dismiss(None)
        else:
            self.dismiss(option_id)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle double-click or enter on the option list."""
        event.stop()
        self.action_select_model()
