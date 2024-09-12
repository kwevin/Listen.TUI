from textual.app import ComposeResult
from textual.containers import Center, Grid, Middle
from textual.lazy import Lazy
from textual.widgets import Label, Markdown, TabbedContent, TabPane

from listentui.listen.client import ListenClient
from listentui.pages.base import BasePage
from listentui.widgets.profileTabs import ActivityTab, FavoritesTab, UploadsTab


class ProfilePage(BasePage):
    DEFAULT_CSS = """
    #main {
        grid-size: 2 3;
        grid-rows: 3 3 1fr;
        align: center middle;
        grid-gutter: 0;
    }

    #bio {
        row-span: 2;
    }

    #stats {
        grid-size: 3 2;
        align-horizontal: center;
    }
    #stats Label {
        width: 1fr;
        content-align: center middle;
    }
    
    TabbedContent {
        column-span: 2;
    }

    TabPane > * {
        width: 1fr;
        height: 1fr;
    }


    """

    def __init__(self) -> None:
        super().__init__()
        self.client = ListenClient.get_instance()
        assert self.client.current_user is not None
        self.user = self.client.current_user

    def compose(self) -> ComposeResult:
        with Grid(id="main"):
            yield Center(Middle(Label("username", id="username")))
            yield Markdown(id="bio")
            with Grid(id="stats"):
                yield Label("Requested")
                yield Label("Favorited")
                yield Label("Uploaded")
                yield Label(id="req")
                yield Label(id="fav")
                yield Label(id="upl")
            with TabbedContent():
                with TabPane("Activity"):
                    yield Lazy(ActivityTab(self.user.feeds))
                with TabPane("Favorites"):
                    yield Lazy(FavoritesTab())
                with TabPane("Uploads"):
                    yield Lazy(UploadsTab())

    def on_mount(self) -> None:
        # note: this will return more than one result, but we only need the first one
        self.query_one("#username", Label).update(self.user.display_name)
        self.query_one(Markdown).update(self.user.bio or "")
        self.query_one("#req", Label).update(str(self.user.requests))
        self.query_one("#fav", Label).update(str(self.user.favorites))
        self.query_one("#upl", Label).update(str(self.user.uploads))
