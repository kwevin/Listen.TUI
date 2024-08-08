from textual.app import ComposeResult
from textual.events import Key
from textual.reactive import var
from textual.screen import Screen
from textual.widgets import Footer, Placeholder, TabbedContent, TabPane

from listentui.data.config import Config
from listentui.pages.home import HomePage
from listentui.utilities import RichLogExtended


class MainScreen(Screen[None]):
    DEFAULT_CSS = """
    MainScreen TabPane {
        width: 1fr;
        height: 1fr;
    }
    """
    index: var[int] = var(0, init=False)

    def __init__(self) -> None:
        super().__init__()
        self.content = ["home", "search", "history", "download", "user", "setting"]

    def watch_index(self, value: int) -> None:
        self.query_one(TabbedContent).active = self.content[value]

    def validate_index(self, value: int) -> int:
        max_idx = len(self.content) - 1
        if value == max_idx + 1:
            value = 0
        elif value == -1:
            value = max_idx

        return value

    def compose(self) -> ComposeResult:
        with TabbedContent():
            with TabPane("Home", id="home"):
                yield HomePage()
            with TabPane("Search", id="search"):
                yield Placeholder()
            with TabPane("History", id="history"):
                yield Placeholder()
            with TabPane("Download", id="download"):
                yield Placeholder()
            with TabPane("User", id="user"):
                yield Placeholder()
            with TabPane("Setting", id="setting"):
                yield Placeholder()
        yield Footer()

    async def on_mount(self) -> None:
        verbose = Config.get_config().advance.stats_for_nerd
        if verbose:
            self.content.insert(len(self.content) - 1, "log")
            self.query_one(TabbedContent).add_pane(TabPane("Log", RichLogExtended(), id="log"), before="setting")

    def on_tabbed_content_tab_activated(self, tab: TabbedContent.TabActivated) -> None:
        tab_id = tab.pane.id
        if not tab_id:
            return
        self.index = self.content.index(tab_id)

    def on_key(self, event: Key) -> None:
        if event.key == "tab":
            event.prevent_default()
            self.index += 1
        elif event.key == "shift+tab":
            event.prevent_default()
            self.index -= 1

    # def on_listen_websocket_updated(self, event: ListenWebsocket.Updated) -> None:
    #     romaji_first = Config.get_config().display.romaji_first
    #     title = event.data.song.format_title(romaji_first=romaji_first)
    #     artist = event.data.song.format_artists(romaji_first=romaji_first)
    #     self.notify(f"{title}" + f" by [{Theme.ACCENT}]{artist}[/]" if artist else "", title="Now Playing")
    #     self.query_one(HistoryPage).update_one()
