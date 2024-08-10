from typing import Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget

from listentui.data.config import Config
from listentui.listen import ListenClient, Song
from listentui.screen.modal import ArtistScreen, SongScreen, SourceScreen
from listentui.widgets.scrollableLabel import ScrollableLabel
from listentui.widgets.vanityBar import VanityBar


class SongContainer(Widget):
    DEFAULT_CSS = """
    SongContainer {
        width: 1fr;
        height: auto;

        # #artist {
        #     color: rgb(249, 38, 114);
        # }
    }
    """
    song: reactive[None | Song] = reactive(None, layout=True, init=False)

    def __init__(self, song: Optional[Song] = None) -> None:
        super().__init__()
        if song:
            self.song = song

    def watch_song(self, song: Song) -> None:
        romaji_first = Config.get_config().display.romaji_first
        self.artist = song.format_artists_list(romaji_first=romaji_first) or []
        self.title = song.format_title(romaji_first=romaji_first) or ""
        self.source = song.format_source(romaji_first=romaji_first)
        self.query_one("#artist", ScrollableLabel).update(
            *[Text.from_markup(f"[red]{artist}[/]") for artist in self.artist]
        )
        self.query_one("#title", ScrollableLabel).update(Text.from_markup(f"{self.title}"))
        if self.source:
            self.query_one("#title", ScrollableLabel).append(Text.from_markup(f"[cyan]\\[{self.source}][/cyan]"))

    def update_song(self, song: Song) -> None:
        self.song = song

    def compose(self) -> ComposeResult:
        yield VanityBar()
        yield ScrollableLabel(id="artist")
        yield ScrollableLabel(id="title", sep=" ")

    async def on_scrollable_label_clicked(self, event: ScrollableLabel.Clicked) -> None:
        if not self.song:
            return
        client = ListenClient.get_instance()
        if event.widget.id == "artist":
            if not self.song.artists:
                return
            artist_id = self.song.artists[event.index].id
            self.app.push_screen(ArtistScreen(artist_id))
        if event.widget.id == "title":
            if event.index == 0:
                self.app.push_screen(SongScreen(self.song.id))
            else:
                if not self.song.source:
                    return
                source_id = self.song.source.id
                self.notify(f"Fetching data for {event.content.plain}...")
                source = await client.source(source_id)
                if not source:
                    return
                self.app.clear_notifications()
                self.app.push_screen(SourceScreen(source))

    def set_tooltips(self, string: str | None) -> None:
        self.query_one("#title", ScrollableLabel).tooltip = string
