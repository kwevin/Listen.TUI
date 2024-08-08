from logging import getLogger

from textual.widget import Widget

from listentui.data.config import Config


class BasePage(Widget, can_focus=True):
    def __init__(
        self,
        id: str | None = None,  # noqa: A002
    ) -> None:
        super().__init__(id=id)
        self.config = Config.get_config()
        self._log = getLogger(__name__)

    def on_show(self) -> None:
        self.focus()
