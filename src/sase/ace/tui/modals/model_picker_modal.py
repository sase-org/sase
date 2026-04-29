"""Model picker modal for selecting a coder LLM model."""

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets._option_list import Option

from .base import OptionListNavigationMixin

# Sentinel returned when user selects "Custom..."
CUSTOM_SENTINEL = "__custom__"


def _build_model_options(*, include_default_option: bool = True) -> list[Option | None]:
    """Build the option list items grouped by provider.

    Args:
        include_default_option: If True (default), prepend the
            ``"Same as planner"`` option that returns ``None``.
            Callers like the temporary-override modal that have no
            "use planner default" semantics pass ``False`` to omit it.
    """
    from sase.llm_provider.registry import model_to_provider_map

    # Group models by provider, preserving insertion order
    provider_models: dict[str, list[str]] = {}
    for model, provider in model_to_provider_map().items():
        provider_models.setdefault(provider, []).append(model)

    items: list[Option | None] = []
    if include_default_option:
        items.append(Option("Same as planner", id="__default__"))

    first_section = not include_default_option
    for provider, models in provider_models.items():
        if not first_section:
            items.append(None)  # separator
        first_section = False
        items.append(
            Option(f"  {provider.upper()}", id=f"__header_{provider}__", disabled=True)
        )
        for model in models:
            items.append(Option(f"    {model}", id=model))

    items.append(None)  # separator
    items.append(Option("  Custom...", id=CUSTOM_SENTINEL))

    return items


class ModelPickerModal(OptionListNavigationMixin, ModalScreen[str | None]):
    """Modal for selecting a coder LLM model.

    Args:
        title: Heading shown above the list.
        include_default_option: If True (default), include the
            ``"Same as planner"`` option whose selection dismisses with
            ``None``.  Pass ``False`` for callers (e.g. the temporary
            override modal) where ``None`` only ever means *cancel*.
    """

    _option_list_id = "model-picker-list"

    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        ("enter", "select_model", "Select"),
    ]

    def __init__(
        self,
        *,
        title: str = "Select Coder Model",
        include_default_option: bool = True,
    ) -> None:
        super().__init__()
        self._title = title
        self._include_default_option = include_default_option

    def compose(self) -> ComposeResult:
        with Container(id="model-picker-container"):
            yield Static(
                f"[bold cyan]{self._title}[/bold cyan]",
                id="model-picker-title",
            )
            yield OptionList(
                *_build_model_options(
                    include_default_option=self._include_default_option,
                ),
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
