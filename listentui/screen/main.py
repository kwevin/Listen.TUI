from textual.app import ComposeResult
from textual.reactive import var
from textual.screen import Screen
from textual.widgets import Footer, Placeholder, TabbedContent, TabPane

from listentui.data.config import Config
from listentui.listen.client import ListenClient
from listentui.pages.history import HistoryPage
from listentui.pages.home import HomePage
from listentui.pages.profile import ProfilePage
from listentui.pages.search import SearchPage
from listentui.pages.setting import SettingPage
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

    def compose(self) -> ComposeResult:
        with TabbedContent(id="topbar"):
            with TabPane("Home", id="home"):
                yield HomePage()
            with TabPane("Search", id="search"):
                yield SearchPage()
            with TabPane("History", id="history"):
                yield HistoryPage()
            with TabPane("Download", id="download"):
                yield Placeholder()
            with TabPane("Setting", id="setting"):
                yield SettingPage()
        yield Footer()

    async def on_mount(self) -> None:
        if ListenClient.get_instance().current_user:
            await self.query_one("#topbar", TabbedContent).add_pane(
                TabPane("Profile", ProfilePage(), id="profile"), before="setting"
            )

        verbose = Config.get_config().advance.stats_for_nerd
        if verbose:
            await self.query_one("#topbar", TabbedContent).add_pane(
                TabPane("Log", RichLogExtended(), id="log"), before="setting"
            )

    # @on(TabbedContent.TabActivated, "#topbar")
    # def on_tabbed_content_tab_activated(self, tab: TabbedContent.TabActivated) -> None:
    #     tab_id = tab.pane.id
    #     if not tab_id:
    #         return
    #     self.index = self.content.index(tab_id)

    # def on_key(self, event: Key) -> None:
    #     if event.key == "tab":
    #         event.prevent_default()
    #         self.index += 1
    #     elif event.key == "shift+tab":
    #         event.prevent_default()
    #         self.index -= 1

    # def on_listen_websocket_updated(self, event: ListenWebsocket.Updated) -> None:
    #     romaji_first = Config.get_config().display.romaji_first
    #     title = event.data.song.format_title(romaji_first=romaji_first)
    #     artist = event.data.song.format_artists(romaji_first=romaji_first)
    #     self.notify(f"{title}" + f" by [{Theme.ACCENT}]{artist}[/]" if artist else "", title="Now Playing")
    #     self.query_one(HistoryPage).update_one()
