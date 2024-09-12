# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false
import logging
from logging import Handler, Logger, LogRecord
from queue import Queue
from typing import Any, ClassVar

from textual.binding import Binding, BindingType
from textual.widgets import RichLog


class RichLogExtended(RichLog):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("c", "clear", "Clear"),
        Binding("d", "toggle_autoscroll", "Toggle Autoscroll"),
        Binding("f", "empty_queue", "Refresh Logs"),
    ]
    queue: Queue[str] = Queue(maxsize=-1)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, max_lines=1000, highlight=True, markup=True, wrap=True, **kwargs)
        self.set_interval(5, self.action_empty_queue)

    def action_clear(self) -> None:
        self.clear()

    def action_toggle_autoscroll(self) -> None:
        self.auto_scroll = not self.auto_scroll
        if self.auto_scroll:
            self.scroll_end()
        self.notify(f"Autoscroll {'enabled' if self.auto_scroll else 'disabled'}")

    def on_resize(self) -> None:
        self.action_empty_queue()

    def action_empty_queue(self) -> None:
        while not RichLogExtended.queue.empty():
            self.write(RichLogExtended.queue.get_nowait())


class RichLogHandler(Handler):
    def emit(self, record: LogRecord) -> None:
        message = self.format(record)
        RichLogExtended.queue.put_nowait(message)


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
