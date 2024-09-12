from __future__ import annotations

from threading import Thread
from typing import Any, ClassVar, Optional, cast

from rich.text import Text
from textual import events, on, work
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Center, Container, Grid, Horizontal, VerticalScroll
from textual.lazy import Lazy
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Button, Collapsible, Label, ListView, Markdown, Static

from listentui.data.theme import Theme
from listentui.listen import ListenClient
from listentui.listen.client import RequestError
from listentui.listen.interface import Album, AlbumID, Artist, ArtistID, Song, SongID, Source, SourceID
from listentui.utilities import format_time_since
from listentui.widgets.buttons import StaticButton, ToggleButton
from listentui.widgets.durationProgressBar import DurationProgressBar
from listentui.widgets.mpvThread import MPVThread, PreviewStatus, PreviewType
from listentui.widgets.scrollableLabel import ScrollableLabel
from listentui.widgets.songListView import (
    SongItem,
    SongListView,
)


class SourceScreen(Screen[None]):
    DEFAULT_CSS = """
    SourceScreen {
        align: center middle;
        background: $background;
        hatch: left $background-lighten-1 60%;
    }
    SourceScreen #box {
        width: 100%;
        margin: 4 4 6 4;
        height: 100%;
        border: thick $background 80%;
        background: $surface;
    }
    SourceScreen Center {
        margin-top: 1;
    }
    SourceScreen Markdown {
        margin: 1 2 0 0;
    }
    SourceScreen > * {
        padding-left: 2;
        padding-right: 2;
    }
    SourceScreen VerticalScroll {
        margin: 1 0;
    }
    SourceScreen SongListView {
        margin-right: 2;
    }
    SourceScreen CollapsibleTitle {
        width: 100%;
        margin-right: 1;
    }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "cancel"),
    ]

    def __init__(self, source_id: SourceID):
        super().__init__()
        self.source_id = source_id
        self.source: Source | None = None

    def compose(self) -> ComposeResult:
        yield EscButton()
        with Container(id="box"):
            if self.source is None:
                return
            yield Center(Label(id="name"))
            yield (
                Collapsible(Markdown(self.source.description_to_markdown()), title="Description")
                if self.source.description
                else Label("- No description -")
            )
            yield Label(id="links")
            with VerticalScroll():
                if self.source.songs:
                    id_to_album = self.id_to_albums(self.source.songs)
                    id_to_song = self.id_to_songs(self.source.songs)
                    for album_id, songs in id_to_song.items():
                        album = id_to_album[album_id]
                        yield Collapsible(
                            Lazy(SongListView(*[SongItem(song) for song in songs], initial_index=None)),
                            title=f"{album.format_name()}\n{len(songs)} Songs",
                        )
                if self.source.songs_without_album:
                    yield Collapsible(
                        Lazy(
                            SongListView(
                                *[SongItem(song) for song in self.source.songs_without_album], initial_index=None
                            )
                        ),
                        title=f"- No source -\n{len(self.source.songs_without_album)} Songs",
                    )

    def id_to_albums(self, songs: list[Song]) -> dict[AlbumID, Album]:
        albums: dict[AlbumID, Album] = {}
        for song in songs:
            if not song.album:
                continue
            if albums.get(song.album.id, None) is None:
                albums[song.album.id] = song.album
        return albums

    def id_to_songs(self, songs: list[Song]) -> dict[AlbumID, list[Song]]:
        albums: dict[AlbumID, list[Song]] = {}
        for song in songs:
            if not song.album:
                continue
            if albums.get(song.album.id, None) is None:
                albums[song.album.id] = []
            albums[song.album.id].append(song)
        return albums

    @on(SongListView.SongSelected)
    async def song_selected(self, event: SongListView.SongSelected) -> None:
        self.app.push_screen(SongScreen(event.song.id))

    @on(SongListView.ArtistSelected)
    async def artist_selected(self, event: SongListView.ArtistSelected) -> None:
        self.app.push_screen(ArtistScreen(event.artist.id))

    @on(ListView.Highlighted)
    def child_highlighed(self, event: ListView.Highlighted) -> None:
        if event.item:
            self.scroll_to_widget(event.item, center=True)

    @work
    async def on_mount(self) -> None:
        self.query_one("#box", Container).loading = True
        self.source = await ListenClient.get_instance().source(self.source_id)
        await self.recompose()
        self.query_one("#box", Container).loading = False
        if self.source is None:
            raise Exception("source cannot be None")
        self.query_one("#name", Label).update(self.source.format_name() or "")
        self.query_one("#links", Label).update(
            f"{self.source.format_socials(sep=' ') or '- No links for this source yet - '}"
        )

    def action_cancel(self) -> None:
        self.dismiss()


class SongScreen(Screen[bool]):
    """Screen for confirming actions"""

    DEFAULT_CSS = """
    SongScreen {
        align: center middle;
        background: $background;
        hatch: left $background-lighten-1 60%;
    }
    SongScreen ScrollableLabel {
        height: 1;
    }
    SongScreen Grid {
        grid-size: 3 4;
        grid-gutter: 1 2;
        grid-rows: 1 3 2 1fr;
        padding: 0 2;
        width: 96;
        height: 14;
        border: thick $background 80%;
        background: $surface;
        border-subtitle-color: red;
        border-title-color: red;
        border-title-align: center;
    }
    SongScreen > Container {
        height: 3;
        width: 100%;
        align: left middle;
    }
    SongScreen Horizontal {
        column-span: 3;
        width: 100%;
        align: center middle;
    }
    SongScreen Horizontal > * {
        margin-right: 1;
    }
    SongScreen StaticButton {
        min-width: 13;
    }
    SongScreen #favorite {
        min-width: 14;
    }
    SongScreen .hidden {
        display: none;
    }
    SongScreen DurationProgressBar {
        offset: 0 1;
    }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "cancel"),
    ]

    def __init__(self, song_id: SongID, favorited: bool | None = None):
        super().__init__()
        self.song_id = song_id
        self.song: Song | None = None
        self.got_favorited = favorited
        self.is_favorited = False

    def compose(self) -> ComposeResult:
        yield EscButton()
        with Grid():
            if self.song is None:
                return

            yield Label("Track/Artist")
            yield Label("Album")
            yield Label("Source")
            yield Container(
                ScrollableLabel(Text.from_markup(self.song.format_title() or ""), id="title"),
                ScrollableLabel(
                    *[Text.from_markup(f"[red]{artist}[/]") for artist in a]
                    if (a := self.song.format_artists_list()) is not None
                    else [],
                    id="artist",
                ),
            )
            album = self.song.format_album()
            source = self.song.format_source()
            yield Container(
                ScrollableLabel(
                    Text.from_markup(f"[green]{album}[/]" if album else ""),
                    id="album",
                )
            )
            yield Container(
                ScrollableLabel(
                    Text.from_markup(f"[cyan]{source}[/]" if source else ""),
                    id="source",
                )
            )
            yield Label(f"Duration: {self.song.duration}", id="duration")
            yield Label(
                f"Last played: {format_time_since(self.song.last_played, True) if self.song.last_played else None}",
                id="last_play",
            )
            yield Label(f"Time played: {self.song.played}", id="time_played")
            with Horizontal(id="horizontal"):
                yield StaticButton("Preview", id="preview")
                yield DurationProgressBar(stop=True, total=0, pause_on_end=True)
                yield ToggleButton("Favorite", "Favorited", check_user=True, hidden=True, id="favorite")
                yield StaticButton("Request", check_user=True, hidden=True, id="request")

    async def on_scrollable_label_clicked(self, event: ScrollableLabel.Clicked) -> None:
        container_id = event.widget.id
        if not container_id:
            return
        if not self.song:
            return
        match container_id:
            case "artist":
                if not self.song.artists:
                    return
                if len(self.song.artists) == 1:
                    self.app.push_screen(ArtistScreen(self.song.artists[0].id))
                else:
                    self.app.push_screen(ArtistScreen(self.song.artists[event.index].id))
            case "album":
                if not self.song.album:
                    return
                self.app.push_screen(AlbumScreen(self.song.album.id))
            case "source":
                if not self.song.source:
                    return
                self.app.push_screen(SourceScreen(self.song.source.id))
            case _:
                return

    def on_mount(self) -> None:
        self.query_one(Grid).loading = True
        self.fetch_song()

    @work
    async def fetch_song(self) -> None:
        client = ListenClient.get_instance()
        song = await client.song(self.song_id)
        if song is None:
            raise Exception("Song cannot be None")
        self.song = song
        await self.recompose()
        self.query_one(Grid).border_subtitle = f"[{self.song.id}]"
        self.query_one(Grid).border_title = f"Uploader: {self.song.uploader.display_name}" if self.song.uploader else ""
        if self.got_favorited:
            self.is_favorited = self.got_favorited
        elif client.logged_in:
            self.is_favorited: bool = await client.check_favorite(song.id) or False
        self.query_one("#favorite", ToggleButton).set_toggle_state(self.is_favorited)
        self.query_one(Grid).loading = False

    def action_cancel(self) -> None:
        Thread(target=MPVThread.terminate_preview, name="terminate_preview", daemon=True).start()
        self.dismiss(self.is_favorited)

    @on(StaticButton.Pressed, "#preview")
    def preview(self) -> None:
        song = cast(Song, self.song)
        if not song.snippet:
            self.notify("No snippet to preview", severity="warning", title="Preview")
            return
        self.query_one("#preview", StaticButton).disabled = True
        MPVThread.preview(song.snippet, self.handle_preview_status)

    def handle_preview_status(self, data: PreviewStatus):  # noqa: PLR0911
        try:
            progress = self.query_one(DurationProgressBar)
            if data.state == PreviewType.LOCKED:
                self.notify("Cannot preview two songs at the same time", title="Preview", severity="warning")
                return
            if data.state == PreviewType.UNABLE:
                self.notify("Unable to play preview :(", title="Preview", severity="warning")
                return
            if data.state == PreviewType.PLAYING:
                progress.reset()
                progress.resume()
                return
            if data.state == PreviewType.DATA:
                cache = cast(MPVThread.DemuxerCacheState, data.other)
                progress.update_total(round(cache.cache_end))
                return
            if data.state == PreviewType.DONE:
                self.query_one("#preview", StaticButton).disabled = False
                return
            if data.state == PreviewType.ERROR:
                self.notify("An error has occured", title="Preview", severity="warning")
                return
        except Exception:
            return

    @on(ToggleButton.Pressed, "#favorite")
    @work
    async def favorite(self) -> None:
        song = cast(Song, self.song)
        self.is_favorited = not self.is_favorited
        self.query_one("#favorite", ToggleButton).set_toggle_state(self.is_favorited)
        client = ListenClient.get_instance()
        await client.favorite_song(song.id)

    @on(StaticButton.Pressed, "#request")
    @work
    async def request(self) -> None:
        song = cast(Song, self.song)
        client = ListenClient.get_instance()
        res: Song | RequestError = await client.request_song(song.id, exception_on_error=False)
        if isinstance(res, Song):
            title = res.format_title()
            artist = res.format_artists()
            self.notify(
                f"{title}" + f" by [{Theme.ACCENT}]{artist}[/]" if artist else "",
                title="Sent to queue",
            )
        elif res == RequestError.FULL:
            self.notify("All requests have been used up for today!", severity="warning")
        else:
            self.notify("Song is already in queue", severity="warning")


class OptionButton(Button):
    def __init__(self, *args: Any, index: int, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.index = index

    class Selected(Message):
        def __init__(self, index: int) -> None:
            super().__init__()
            self.index = index

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.post_message(self.Selected(self.index))


class SelectionScreen(Screen[int | None]):
    """Screen for confirming actions"""

    DEFAULT_CSS = """
    SelectionScreen {
        align: center middle;
        background: $background;
        hatch: left $background-lighten-1 60%;
    }
    SelectionScreen Container {
        width: auto;
        height: auto;
        border: thick $background 80%;
        background: $surface;
    }
    SelectionScreen Label {
        height: auto;
        width: 100%;
        content-align: center middle;
        margin-left: 1;
    }
    SelectionScreen Grid {
        grid-size: 2;
        grid-gutter: 1 2;
        padding: 1 1;
        width: 60;
        height: auto;
    }
    SelectionScreen OptionButton {
        width: 100%;
    }
    SelectionScreen Center {
        width: 100%;
        height: auto;
    }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape,n,N", "cancel"),
        ("left,h", "focus_previous"),
        ("right,l", "focus_next"),
        ("up,k", "focus_up"),
        ("down,j", "focus_down"),
    ]

    def __init__(self, options: list[str]):
        super().__init__()
        self.options = options

    def compose(self) -> ComposeResult:
        with Container():
            yield Label("Select one")
            with Grid():
                for idx, option in enumerate(self.options):
                    yield OptionButton(self.clamp(f"[{idx + 1}] {option}"), index=idx)
            with Center():
                yield Button("[N] Cancel", variant="primary", id="cancel")

    @on(Button.Pressed, "#cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_focus_up(self) -> None:
        # what the fuck am i doing
        self.focus_previous()
        self.focus_previous()

    def action_focus_down(self) -> None:
        # if it works it works
        self.focus_next()
        self.focus_next()

    def on_option_button_selected(self, event: OptionButton.Selected) -> None:
        self.dismiss(event.index)

    def on_key(self, event: events.Key) -> None:
        if event.key.isdigit() and event.key != "0" and int(event.key) <= len(self.options):
            self.dismiss(int(event.key) - 1)

    def clamp(self, text: str) -> str:
        min_len = 24
        return text if len(text) <= min_len else text[: min_len - 1] + "…"


class ArtistButton(Button):
    DEFAULT_CSS = f"""
    ArtistButton {{
        background: {Theme.BUTTON_BACKGROUND};
        max-width: 16;
        max-height: 3;
    }}
    """

    def __init__(self, artist_id: ArtistID, name: str):
        super().__init__(self.clamp(name))
        self.can_focus = False
        self.artist_id = artist_id

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        self.app.push_screen(ArtistScreen(self.artist_id))

    def clamp(self, text: str) -> str:
        max_length = 16
        return text if len(text) <= max_length else text[: max_length - 1] + "…"


class AlbumScreen(Screen[None]):
    DEFAULT_CSS = """
    AlbumScreen {
        align: center middle;
        background: $background;
        hatch: left $background-lighten-1 60%;
    }
    AlbumScreen #box {
        width: 100%;
        margin: 4 4 6 4;
        height: 100%;
        border: thick $background 80%;
        background: $surface;
    }
    AlbumScreen Center {
        margin-top: 1;
    }
    AlbumScreen Horizontal {
        width: 100%;
        height: auto;
        margin-bottom: 1;
    }
    AlbumScreen Horizontal Label {
        margin-right: 1;
    }
    AlbumScreen > * {
        padding-left: 2;
        padding-right: 2;
    }
    AlbumScreen VerticalScroll {
        margin: 1 0;
    }
    AlbumScreen Collapsible {
        margin: 1 0;
    }
    AlbumScreen SongListView {
        margin-right: 2;
    }
    AlbumScreen Collapsible Grid {
        grid-size: 5;
        grid-gutter: 1 2;
        grid-rows: 5;
        height: auto;
    }
    AlbumScreen CollapsibleTitle {
        width: 100%;
        margin-right: 1;
    }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "cancel"),
    ]

    def __init__(self, album_id: AlbumID, album: Album | None = None):
        super().__init__()
        self.album_id = album_id
        self.album: Album | None = None

    def compose(self) -> ComposeResult:
        yield EscButton()
        with Container(id="box"):
            if self.album is None:
                return
            yield Center(Label(id="name"))
            yield Label(id="links")
            with VerticalScroll():
                if self.album.artists:
                    with Collapsible(title="Contributing artists:"), Grid():
                        for artist in self.album.artists:
                            yield ArtistButton(artist.id, artist.format_name() or "")
                if self.album.songs:
                    with VerticalScroll():
                        yield Lazy(SongListView(*[SongItem(song) for song in self.album.songs], initial_index=None))

    @on(SongListView.SongSelected)
    async def song_selected(self, event: SongListView.SongSelected) -> None:
        self.app.push_screen(SongScreen(event.song.id))

    @on(SongListView.ArtistSelected)
    async def artist_selected(self, event: SongListView.ArtistSelected) -> None:
        self.app.push_screen(ArtistScreen(event.artist.id))

    @on(ListView.Highlighted)
    def child_highlighed(self, event: ListView.Highlighted) -> None:
        if event.item:
            self.scroll_to_widget(event.item, center=True)

    @work
    async def on_mount(self) -> None:
        if not self.album:
            self.query_one("#box", Container).loading = True
            self.album = await ListenClient.get_instance().album(self.album_id)
            if self.album is None:
                raise Exception("album cannot be None")

            await self.recompose()
        count = len(self.album.songs) if self.album.songs else 0
        self.query_one("#name", Label).update(f"{self.album.format_name()} - {count} Songs")
        self.query_one("#links", Label).update(
            f"{self.album.format_socials(sep=' ') or '- No links for this album yet -'}"
        )
        self.query_one("#box", Container).loading = False

    def action_cancel(self) -> None:
        self.dismiss()


class ArtistScreen(Screen[None]):
    DEFAULT_CSS = """
    ArtistScreen {
        align: center middle;
        background: $background;
        hatch: left $background-lighten-1 60%;
    }
    ArtistScreen #box {
        width: 100%;
        margin: 4 4 6 4;
        height: 100%;
        border: thick $background 80%;
        background: $surface;
    }
    ArtistScreen Center {
        margin-top: 1;
    }
    ArtistScreen Horizontal {
        width: 100%;
        height: auto;
        margin-bottom: 1;
    }
    ArtistScreen Horizontal Label {
        margin-right: 1;
    }
    ArtistScreen > * {
        padding-left: 2;
        padding-right: 2;
    }
    ArtistScreen VerticalScroll {
        margin: 1 0;
    }
    ArtistScreen SongListView {
        margin-right: 2;
    }
    ArtistScreen CollapsibleTitle {
        width: 100%;
        margin-right: 1;
    }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "cancel"),
    ]

    def __init__(self, artist_id: ArtistID):
        super().__init__()
        self.artist_id = artist_id
        self.artist: Artist | None = None

    def compose(self) -> ComposeResult:
        # lazy for the win!!
        yield EscButton()
        with Container(id="box"):  # noqa: PLR1702
            if self.artist is None:
                return
            yield Center(Label(id="name"))
            with Horizontal():
                yield Label(id="albums-count")
                yield Label(id="songs-count")
            yield Label(id="links")
            with VerticalScroll():
                if self.artist.albums:
                    for album in self.artist.albums:
                        if album.songs:
                            with Collapsible(title=f"{album.format_name()}\n{len(album.songs)} Songs"), Lazy(
                                SongListView(initial_index=None)
                            ):
                                yield from [SongItem(song) for song in album.songs]

                if self.artist.songs_without_album:
                    with Collapsible(title=f"- No album -\n{len(self.artist.songs_without_album)} Songs"), Lazy(
                        SongListView(initial_index=None)
                    ):
                        yield from [SongItem(song) for song in self.artist.songs_without_album]

    @on(SongListView.SongSelected)
    async def song_selected(self, event: SongListView.SongSelected) -> None:
        client = ListenClient.get_instance()
        favorited = False
        if client.logged_in:
            favorited = await client.check_favorite(event.song.id)
        self.app.push_screen(SongScreen(event.song.id, favorited=favorited))

    @on(SongListView.ArtistSelected)
    async def artist_selected(self, event: SongListView.ArtistSelected) -> None:
        if event.artist == self.artist:
            return
        self.app.push_screen(ArtistScreen(event.artist.id))

    @on(ListView.Highlighted)
    def child_highlighed(self, event: ListView.Highlighted) -> None:
        if event.item:
            self.scroll_to_widget(event.item, center=True)

    async def on_mount(self) -> None:
        self.query_one("#box", Container).loading = True
        self.fetch_artist()

    @work
    async def fetch_artist(self) -> None:
        client = ListenClient.get_instance()
        artist = await client.artist(self.artist_id)
        if artist is None:
            raise Exception("Cannot be None")
        self.artist = artist
        await self.recompose()
        self.query_one("#name", Label).update(self.artist.format_name() or "")
        self.query_one("#albums-count", Label).update(f"{self.artist.album_count or 'No'} Albums")
        self.query_one("#songs-count", Label).update(f"- {self.artist.song_count or 'No'} Songs")
        self.query_one("#links", Label).update(f"{self.artist.format_socials(sep=' ', use_app=True) or 'No Socials'}")
        self.query_one("#box", Container).loading = False

    def action_cancel(self) -> None:
        self.dismiss()


class ConfirmScreen(Screen[bool]):
    """Screen for confirming actions"""

    DEFAULT_CSS = """
    ConfirmScreen {
        align: center middle;
        background: $background;
        hatch: left $background-lighten-1 60%;
    }

    ConfirmScreen #dialog {
        grid-size: 2;
        grid-gutter: 1 2;
        grid-rows: 1fr 3;
        padding: 0 1;
        width: 60;
        height: 11;
        border: thick $background 80%;
        background: $surface;
    }

    ConfirmScreen #question {
        column-span: 2;
        height: 1fr;
        width: 1fr;
        content-align: center middle;
    }

    ConfirmScreen Button {
        width: 100%;
    }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape,n,N", "cancel"),
        ("enter,y,Y", "confirm"),
        ("left", "focus_previous"),
        ("right", "focus_next"),
    ]

    def __init__(
        self,
        label: Optional[str] = None,
        option_true: Optional[str] = None,
        option_false: Optional[str] = None,
    ):
        super().__init__()
        self.label = label or "Are you sure you want to proceed"
        self.option_true = option_true or "Confirm"
        self.option_false = option_false or "Cancel"

    def compose(self) -> ComposeResult:
        yield Grid(
            Label(self.label, id="question"),
            Button(f"[Y] {self.option_true}", variant="error", id="confirm"),
            Button(f"[N] {self.option_false}", variant="primary", id="cancel"),
            id="dialog",
        )

    @on(Button.Pressed, "#confirm")
    def action_confirm(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#cancel")
    def action_cancel(self) -> None:
        self.dismiss(False)


class TestScreen(Screen[None]):
    DEFAULT_CSS = """
    TestScreen {
        align: center middle;
        background: $background;
    }
    """

    def compose(self) -> ComposeResult:
        yield ScrollableLabel(Text("test"), Text("even more test"))

    def on_click(self, event: events.Click) -> None:
        self.dismiss()


class EscButton(Static):
    DEFAULT_CSS = """
    EscButton {
        dock: top;
        offset: 2 1;
        width: 7;
        padding: 0 0 !important;
        margin: 0 0 !important;
    }
    """

    def __init__(self) -> None:
        super().__init__("[@click=screen.cancel]< (Esc)[/]", id="esc")
