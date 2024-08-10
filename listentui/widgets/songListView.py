from __future__ import annotations

from rich.text import Text
from textual import events, on
from textual.containers import Grid
from textual.message import Message
from textual.widgets import ListItem, ListView

from listentui.data.config import Config
from listentui.data.theme import Theme
from listentui.listen import ListenClient, Song
from listentui.listen.types import Artist
from listentui.widgets.buttons import StaticButton, ToggleButton
from listentui.widgets.scrollableLabel import ScrollableLabel


class SongItem(ListItem):
    SCOPED_CSS = False
    DEFAULT_CSS = """
    SongItem {
        padding: 1 0 1 0;
    }
    SongItem ScrollableLabel {
        margin-left: 1;
        width: auto;
    }
    SongItem > Widget :hover {
        background: $boost !important;
    }
    SongListView SongItem :hover {
        background: $boost !important;
    }
    SongListView > SongItem.--highlight {
        background: $background-lighten-1;
    }
    SongListView:focus > SongItem.--highlight {
        background: $background-lighten-1;
    }
    """

    def __init__(self, song: Song):
        self.song = song
        romaji_first = Config.get_config().display.romaji_first
        title = song.format_title(romaji_first=romaji_first)
        artists = song.format_artists_list(romaji_first=romaji_first) or []
        super().__init__(
            ScrollableLabel(
                Text.from_markup(f"{title}"),
                classes="item-title",
            ),
            ScrollableLabel(
                *[Text.from_markup(f"[{Theme.ACCENT}]{artist}[/]") for artist in artists],
                classes="item-artist",
            ),
        )

    class SongChildClicked(Message):
        """For informing with the parent ListView that we were clicked"""

        def __init__(self, item: SongItem) -> None:
            super().__init__()
            self.item = item

    class SongLabelClicked(Message):
        def __init__(self, artist: Artist) -> None:
            super().__init__()
            self.artist = artist

    @on(ScrollableLabel.Clicked)
    def scroll_label_clicked(self, event: ScrollableLabel.Clicked) -> None:
        event.stop()
        if self.song.artists is None:
            return
        artist = self.song.artists[event.index]
        self.post_message(self.SongLabelClicked(artist))

    async def _on_click(self, _: events.Click) -> None:
        if any(label.mouse_hover for label in self.query(ScrollableLabel)):
            return
        self.post_message(self.SongChildClicked(self))


class ButtonSongItem(ListItem):
    SCOPED_CSS = False
    DEFAULT_CSS = """
    ButtonSongItem {
        padding: 1 0 1 0;
    }
    ButtonSongItem ScrollableLabel {
        margin-left: 1;
        width: auto;
    }
    SongListView ButtonSongItem :hover {
        background: $boost !important;
    }
    SongListView > ButtonSongItem.--highlight {
        background: $boost;
    }
    SongListView:focus > ButtonSongItem.--highlight {
        background: $boost;
    }
    ButtonSongItem Grid {
        grid-size: 3 3;
        grid-columns: 1fr 16 16;
        grid-rows: 1;
        grid-gutter: 0 1;
        margin-right: 1;
    }
    ButtonSongItem #favorite {
        row-span: 3;
    }
    ButtonSongItem #request {
        row-span: 3;
    }
    """

    def __init__(self, song: Song, favorited: bool = False):
        self.song = song
        self.favorited = False
        romaji_first = Config.get_config().display.romaji_first
        title = song.format_title(romaji_first=romaji_first)
        artists = song.format_artists_list(romaji_first=romaji_first) or []
        logged_in = ListenClient.get_instance().logged_in
        if logged_in:
            super().__init__(
                Grid(
                    ScrollableLabel(
                        Text.from_markup(f"{title}"),
                        classes="item-title",
                    ),
                    ToggleButton("Favorite", "Favorited", True, True, favorited, id="favorite"),
                    StaticButton("Request", True, True, id="request"),
                    ScrollableLabel(
                        *[Text.from_markup(f"[{Theme.ACCENT}]{artist}[/]") for artist in artists],
                        classes="item-artist",
                    ),
                )
            )
        else:
            super().__init__(
                ScrollableLabel(
                    Text.from_markup(f"{title}"),
                    classes="item-title",
                ),
                ScrollableLabel(
                    *[Text.from_markup(f"[{Theme.ACCENT}]{artist}[/]") for artist in artists],
                    classes="item-artist",
                ),
            )

    class SongChildClicked(Message):
        """For informing with the parent ListView that we were clicked"""

        def __init__(self, item: ButtonSongItem) -> None:
            super().__init__()
            self.item = item

    class SongLabelClicked(Message):
        def __init__(self, artist: Artist) -> None:
            super().__init__()
            self.artist = artist

    @on(ScrollableLabel.Clicked, ".item-artist")
    def scroll_label_clicked(self, event: ScrollableLabel.Clicked) -> None:
        event.stop()
        if self.song.artists is None:
            return
        artist = self.song.artists[event.index]
        self.post_message(self.SongLabelClicked(artist))

    async def _on_click(self, _: events.Click) -> None:
        if any(label.mouse_hover for label in self.query(ScrollableLabel)):
            return
        self.post_message(self.SongChildClicked(self))


class SongListView(ListView):
    DEFAULT_CSS = """
    SongListView {
        height: auto;
    }
    SongListView SongItem {
        margin-bottom: 1;
        background: $background-lighten-1;
    }
    SongListView ButtonSongItem {
        margin-bottom: 1;
        background: $background-lighten-1;
    }
    """

    class SongSelected(Message):
        def __init__(self, song: Song) -> None:
            super().__init__()
            self.song = song

    class ArtistSelected(Message):
        def __init__(self, artist: Artist) -> None:
            super().__init__()
            self.artist = artist

    @on(ButtonSongItem.SongChildClicked)
    @on(SongItem.SongChildClicked)
    def song_clicked(self, event: SongItem.SongChildClicked) -> None:
        event.stop()
        self.post_message(self.SongSelected(event.item.song))

    @on(ButtonSongItem.SongLabelClicked)
    @on(SongItem.SongLabelClicked)
    def song_label_clicked(self, event: SongItem.SongLabelClicked) -> None:
        event.stop()
        self.post_message(self.ArtistSelected(event.artist))

    def action_select_cursor(self) -> None:
        selected_child: SongItem | None = self.highlighted_child  # type: ignore
        if selected_child is None:
            return
        self.post_message(self.SongSelected(selected_child.song))
