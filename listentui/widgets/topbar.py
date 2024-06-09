from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Button, Static

from listentui.data import Theme


class NavButton(Button):
    DEFAULT_CSS = f"""
    NavButton {{
        background: {Theme.BUTTON_BACKGROUND};
    }}
    NavButton.-selected {{
        tint: black 20%;
    }}
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.can_focus = False


class Topbar(Widget):
    DEFAULT_CSS = f"""
    Topbar {{
        width: 100%;
        max-height: 3;
        dock: top;
    }}

    Topbar NavButton {{
        width: auto;
    }}

    Topbar #filler {{
        width: 1fr;
        height: 100%;
        background: {Theme.BACKGROUND}
    }}
    """

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield NavButton("Home", classes="navbutton", id="home")
            yield NavButton("Search", classes="navbutton", id="search")
            yield NavButton("History", classes="navbutton", id="history")
            yield NavButton("Terminal", classes="navbutton", id="terminal")
            yield Static(id="filler")
            yield NavButton("User", classes="navbutton", id="user")
            yield NavButton("Info", classes="navbutton", id="_rich-log")
            yield NavButton("Setting", classes="navbutton", id="setting")
