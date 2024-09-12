from typing import ClassVar, cast

from rich.text import Text
from textual import events, on, work
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import ScrollableContainer
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView

from listentui.listen.client import ListenClient
from listentui.listen.interface import ArtistID, Song, SystemFeed
from listentui.screen.modal import AlbumScreen, ArtistScreen, SongScreen, SourceScreen
from listentui.utilities import format_time_since
from listentui.widgets.pageSwitcher import PageSwitcher
from listentui.widgets.songListView import AdvSongItem, SongListView


class FeedItem(ListItem):
    SCOPED_CSS = False
    DEFAULT_CSS = """
    FeedItem {
        padding: 1 0 1 0;
    }
    FeedItem Label {
        margin-left: 1;
        width: auto;
        link-color: rgb(249, 38, 114);
    }
    FeedItem > Widget :hover {
        background: $boost !important;
    }
    FeedView FeedItem :hover {
        background: $boost !important;
    }
    FeedView > FeedItem.--highlight {
        background: $background-lighten-1;
    }
    FeedView:focus > FeedItem.--highlight {
        background: $background-lighten-1;
    }

    FeedItem.favorited {
        border-left: inner red;
    }

    FeedItem.uploaded {
        border-left: inner green;
    }
    """

    def __init__(self, song: Song, feed: SystemFeed):
        super().__init__()
        self.song = song
        self.feed = feed
        self.title = song.format_title()
        artists = song.format_artists_list(show_character=False) or []
        _artist: list[str] = []
        if self.song.artists:
            for idx, artist in enumerate(artists):
                _artist.append(f"[@click=focused.handle_artist('{self.song.artists[idx].id}')]{artist}[/]")
        self.artists = ", ".join(_artist)
        self.set_class(feed.type == SystemFeed.ActivityType.FAVORITED, "favorited")
        self.set_class(feed.type == SystemFeed.ActivityType.UPLOADED, "uploaded")

    def compose(self) -> ComposeResult:
        yield Label(
            Text.from_markup(f"[red]•[/] {format_time_since(self.feed.created_at)}"),
            classes="feed-time",
        )

        yield Label(
            Text.from_markup(f"{self.feed.activity} {self.title} by {self.artists}"),
            classes="feed-text",
        )

    class FeedChildClicked(Message):
        """For informing with the parent ListView that we were clicked"""

        def __init__(self, item: "FeedItem") -> None:
            self.item = item
            super().__init__()

    async def _on_click(self, _: events.Click) -> None:
        self.post_message(self.FeedChildClicked(self))


class FeedView(ListView):
    DEFAULT_CSS = """
    FeedView {
        height: 100%;
    }
    FeedView FeedItem {
        margin-bottom: 1;
        background: $background-lighten-1;
    }
    """

    class FeedSelected(Message):
        def __init__(self, song: Song, feed: SystemFeed, item: FeedItem) -> None:
            self.song = song
            self.feed = feed
            self.item = item
            super().__init__()

    class ArtistSelected(Message):
        def __init__(self, artis_id: ArtistID) -> None:
            self.artis_id = artis_id
            super().__init__()

    @on(FeedItem.FeedChildClicked)
    def feed_clicked(self, event: FeedItem.FeedChildClicked) -> None:
        self.post_message(self.FeedSelected(event.item.song, event.item.feed, event.item))

    def action_handle_artist(self, artist_id: str) -> None:
        self.post_message(self.ArtistSelected(ArtistID(int(artist_id))))

    def action_select_cursor(self) -> None:
        """Select the current item in the list."""
        selected_child: FeedItem | None = cast(FeedItem | None, self.highlighted_child)
        if selected_child is None:
            return
        self.post_message(self.FeedSelected(selected_child.song, selected_child.feed, selected_child))


class ProfileTab(Widget):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+r", "refresh", "Refresh"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.should_reload = False

    def on_show(self) -> None:
        if not self.should_reload:
            return
        self.action_refresh()
        self.should_reload = False

    def on_hide(self) -> None:
        self.should_reload = True

    def action_refresh(self) -> None: ...


class ActivityTab(ProfileTab):
    DEFAULT_CSS = """
    ActivityTab {
        height: 100%;
    }
    """

    def __init__(self, feeds: list[SystemFeed]) -> None:
        super().__init__()
        self.starter = feeds
        self.client = ListenClient.get_instance()

    @work
    async def populate_feeds(self) -> None:
        self.loading = True
        feedview = self.query_one(FeedView)
        await feedview.clear()
        res = (await self.client.update_current_user()).feeds
        await feedview.extend([FeedItem(feed.song, feed) for feed in res if feed.song])
        self.loading = False

    def compose(self) -> ComposeResult:
        yield FeedView(*[FeedItem(feed.song, feed) for feed in self.starter if feed.song])

    @on(FeedView.FeedSelected)
    @work
    async def feed_selected(self, event: FeedView.FeedSelected) -> None:
        song_id = event.song.id
        favorited = event.feed.type == SystemFeed.ActivityType.FAVORITED

        res = await self.app.push_screen_wait(SongScreen(song_id, favorited))

        if res != favorited:
            self.action_refresh()

    @on(FeedView.ArtistSelected)
    async def artist_selected(self, event: FeedView.ArtistSelected) -> None:
        self.app.push_screen(ArtistScreen(event.artis_id))

    def action_refresh(self) -> None:
        self.populate_feeds()


class FavoritesTab(ProfileTab):
    def __init__(self) -> None:
        super().__init__()
        self.should_reload = True
        self.per_page = 20
        self.client = ListenClient.get_instance()
        user = self.client.current_user
        assert user is not None
        self.user = user

    def compose(self) -> ComposeResult:
        with ScrollableContainer():
            yield SongListView()
            yield PageSwitcher.calculate(self.per_page, self.user.favorites)

    @work
    async def populate_list(self, page: int) -> None:
        container = self.query_one(ScrollableContainer)
        container.loading = True
        list_view = self.query_one(SongListView)
        await list_view.clear()
        res = await self.client.user_favorites(self.user.username, (page - 1) * self.per_page, self.per_page)
        await list_view.extend(AdvSongItem(song, True) for song in res)
        container.scroll_home()
        container.loading = False

    @on(PageSwitcher.PageChanged)
    def page_changed(self, event: PageSwitcher.PageChanged) -> None:
        self.populate_list(event.page)

    def action_refresh(self) -> None:
        self.query_one(PageSwitcher).reset()
        self.populate_list(1)

    @on(SongListView.SongSelected)
    @work
    async def song_selected(self, event: SongListView.SongSelected) -> None:
        favorited_status = await self.app.push_screen_wait(SongScreen(event.song.id, True))
        if favorited_status is not True:
            self.query_exactly_one(SongListView).remove_children(f"#_song-{event.song.id}")

    @on(SongListView.ArtistSelected)
    async def artist_selected(self, event: SongListView.ArtistSelected) -> None:
        self.app.push_screen(ArtistScreen(event.artist.id))

    @on(SongListView.SourceSelected)
    async def source_selected(self, event: SongListView.SourceSelected) -> None:
        self.app.push_screen(SourceScreen(event.source.id))

    @on(SongListView.AlbumSelected)
    async def album_selected(self, event: SongListView.AlbumSelected) -> None:
        self.app.push_screen(AlbumScreen(event.album.id))


class UploadsTab(ProfileTab):
    def __init__(self) -> None:
        super().__init__()
        self.should_reload = True
        self.per_page = 20
        self.client = ListenClient.get_instance()
        user = self.client.current_user
        assert user is not None
        self.user = user

    def compose(self) -> ComposeResult:
        with ScrollableContainer():
            yield SongListView()
            yield PageSwitcher.calculate(self.per_page, self.user.uploads)

    @work
    async def populate_list(self, page: int) -> None:
        self.query_one(ScrollableContainer).loading = True
        list_view = self.query_one(SongListView)
        await list_view.clear()
        res = await self.client.user_uploads(self.user.username, (page - 1) * self.per_page, self.per_page)
        await list_view.extend(AdvSongItem(song, True) for song in res)
        self.query_one(ScrollableContainer).loading = False

    @on(PageSwitcher.PageChanged)
    def page_changed(self, event: PageSwitcher.PageChanged) -> None:
        self.populate_list(event.page)

    def action_refresh(self) -> None:
        self.query_one(PageSwitcher).reset()
        self.populate_list(1)

    @on(SongListView.SongSelected)
    @work
    async def song_selected(self, event: SongListView.SongSelected) -> None:
        favorited_status = await self.app.push_screen_wait(SongScreen(event.song.id, True))
        if favorited_status is not True:
            self.query_exactly_one(SongListView).remove_children(f"#_song-{event.song.id}")

    @on(SongListView.ArtistSelected)
    async def artist_selected(self, event: SongListView.ArtistSelected) -> None:
        self.app.push_screen(ArtistScreen(event.artist.id))

    @on(SongListView.SourceSelected)
    async def source_selected(self, event: SongListView.SourceSelected) -> None:
        self.app.push_screen(SourceScreen(event.source.id))

    @on(SongListView.AlbumSelected)
    async def album_selected(self, event: SongListView.AlbumSelected) -> None:
        self.app.push_screen(AlbumScreen(event.album.id))
