from typing import Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget

from listentui.listen import Song
from listentui.screen.modal import ArtistScreen, SongScreen, SourceScreen
from listentui.widgets.scrollableLabel import ScrollableLabel


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
        self._optional_song = song

    def watch_song(self, song: Song) -> None:
        self.artist = song.format_artists_list() or []
        self.title = song.format_title() or ""
        self.source = song.format_source()
        self.query_one("#artist", ScrollableLabel).update(
            *[Text.from_markup(f"[red]{artist}[/]") for artist in self.artist]
        )
        self.query_one("#title", ScrollableLabel).update(Text.from_markup(f"{self.title}"))
        if self.source:
            self.query_one("#title", ScrollableLabel).append(Text.from_markup(f"[cyan]\\[{self.source}][/cyan]"))

    def update_song(self, song: Song) -> None:
        self.song = song

    def compose(self) -> ComposeResult:
        yield ScrollableLabel(id="artist")
        yield ScrollableLabel(id="title", sep=" ")

    def on_mount(self) -> None:
        if self._optional_song:
            self.watch_song(self._optional_song)

    async def on_scrollable_label_clicked(self, event: ScrollableLabel.Clicked) -> None:
        if not self.song:
            return
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
                self.app.push_screen(SourceScreen(source_id))

    def set_tooltips(self, string: str | None) -> None:
        self.query_one("#title", ScrollableLabel).tooltip = string
