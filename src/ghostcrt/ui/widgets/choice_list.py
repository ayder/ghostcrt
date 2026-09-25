from rich.text import Text
from textual.widgets import OptionList


class ChoiceList(OptionList):
    """Single-choice rows with a cursor marker independent of theme color."""

    def on_mount(self) -> None:
        self._labels = [str(option.prompt) for option in self.options]
        self._mark_cursor()

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        self._mark_cursor()

    def _mark_cursor(self) -> None:
        if not hasattr(self, "_labels"):
            return
        for index, label in enumerate(self._labels):
            disabled = self.get_option_at_index(index).disabled
            marker = "> " if index == self.highlighted and not disabled else "  "
            self.replace_option_prompt_at_index(index, Text(marker + label))
