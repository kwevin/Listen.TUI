# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false
import logging
import sys
from datetime import datetime
from logging import Handler, Logger, LogRecord
from typing import Any, ClassVar

from textual._context import active_app  # noqa: PLC2701
from textual.binding import Binding, BindingType
from textual.css.query import QueryError
from textual.widgets import RichLog


class RichLogExtended(RichLog):
    BINDINGS: ClassVar[list[BindingType]] = [Binding("c", "clear", "Clear")]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, highlight=True, markup=True, wrap=True, auto_scroll=False, **kwargs)

    def action_clear(self) -> None:
        self.clear()


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
                for widget in app.query(RichLogExtended):
                    widget.write(message)
            except QueryError:
                pass


def get_logger() -> Logger:
    return logging.getLogger("ListenTUI")


def create_logger(verbose: bool) -> Logger:
    level = logging.DEBUG if verbose else logging.ERROR
    logging.basicConfig(
        level=level,
        format="(%(asctime)s)[%(levelname)s] %(name)s: %(message)s",
        handlers=[RichLogHandler()],
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("ListenTUI")
    logger.debug(f"Logging started at: {datetime.now()}")
    return logger
