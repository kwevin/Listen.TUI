# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false
import logging
import sys
from logging import Handler, Logger, LogRecord
from typing import Any, ClassVar

from textual._context import active_app  # noqa: PLC2701
from textual.binding import Binding, BindingType
from textual.css.query import QueryError
from textual.widgets import RichLog


class RichLogExtended(RichLog):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("c", "clear", "Clear"),
        Binding("d", "toggle_autoscroll", "Toggle Autoscroll"),
    ]
    data: ClassVar[list[str]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, highlight=True, markup=True, wrap=True, **kwargs)
        for line in self.data:
            self.write(line, expand=True)

    def action_clear(self) -> None:
        self.clear()
        RichLogExtended.data = []

    def action_toggle_autoscroll(self) -> None:
        self.auto_scroll = not self.auto_scroll
        self.scroll_end()
        self.notify(f"Autoscroll {'enable' if self.auto_scroll else 'disable'}")

    def on_resize(self) -> None:
        self.clear()
        for line in self.data:
            self.write(line, expand=True)


class RichLogHandler(Handler):
    def emit(self, record: LogRecord) -> None:
        message = self.format(record)
        try:
            app = active_app.get()
        except LookupError:
            print(message, file=sys.stdout)
        else:
            app.log.logging(message)
            # write to all RichLogExtended widgets
            try:
                RichLogExtended.data.append(self.format(record))
                for widget in app.query(RichLogExtended):
                    widget.write(message)
            except QueryError:
                pass


def get_logger() -> Logger:
    return logging.getLogger("LISTENtui")


def create_logger(verbose: bool) -> Logger:
    level = logging.DEBUG if verbose else logging.ERROR
    logging.basicConfig(
        level=level,
        format="(%(asctime)s)[%(levelname)s] %(name)s: %(message)s",
        handlers=[RichLogHandler()],
        datefmt="%H:%M:%S",
    )
    return logging.getLogger("LISTENtui")
