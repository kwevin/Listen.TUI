from typing import Any

from rich.text import Text
from textual.message import Message
from textual.reactive import var
from textual.widgets import Button

from listentui.listen import ListenClient


class StaticButton(Button):
    DEFAULT_CSS = """
    StaticButton:disabled {
        tint: black 80%;
    }
    StaticButton.hidden {
        visibility: hidden;
    }
    """

    def __init__(
        self, label: str | Text | None = None, check_user: bool = False, hidden: bool = False, *args: Any, **kwargs: Any
    ):
        super().__init__(label, *args, **kwargs)
        self.can_focus = False
        self._check_user = check_user
        self._hidden = hidden

    async def on_mount(self) -> None:
        if self._check_user:
            client = ListenClient.get_instance()
            if not client.logged_in:
                self.disabled = True
                if self._hidden:
                    self.add_class("hidden")


class ToggleButton(StaticButton):
    DEFAULT_CSS = """
    ToggleButton.-toggled {
        background: red;
        text-style: bold reverse;
    }
    """
    is_toggled: var[bool] = var(False, init=False)

    class Toggled(Message):
        def __init__(self, state: bool) -> None:
            super().__init__()
            self.state = state

    def __init__(
        self,
        label: str | Text | None = None,
        toggled_label: str | Text | None = None,
        check_user: bool = False,
        hidden: bool = False,
        toggled: bool = False,
        *args: Any,
        **kwargs: Any,
    ):
        super().__init__(label, check_user, hidden, *args, **kwargs)
        self._default = label
        self._toggled_label = toggled_label
        self.is_toggled = toggled

    def watch_is_toggled(self, new: bool) -> None:
        self.toggle_class("-toggled")
        if new and self._toggled_label:
            self.label = self._toggled_label
        else:
            self.label = self._default or ""

    def toggle_state(self) -> None:
        self.is_toggled = not self.is_toggled
        self.post_message(self.Toggled(self.is_toggled))

    def set_toggle_state(self, state: bool) -> None:
        self.is_toggled = state
        self.post_message(self.Toggled(self.is_toggled))

    def update_toggle_label(self, label: str | Text | None) -> None:
        self._toggled_label = label

    def update_default_label(self, label: str | Text | None) -> None:
        self._default = label
