# import webbrowser
from random import choice as random_choice
from typing import ClassVar

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Center, Horizontal
from textual.reactive import var
from textual.validation import Function
from textual.widgets import Input, Label, Select

from listentui.data.config import Config
from listentui.listen.client import ListenClient, RequestError
from listentui.listen.types import Song, SongID
from listentui.pages.base import BasePage
from listentui.screen.modal import ArtistScreen, SongScreen
from listentui.widgets.songListView import ButtonSongItem, SongListView


class SearchPage(BasePage):
    DEFAULT_CSS = """
    SearchPage {
        align: center middle;

        & SongListView {
            height: 100%;
            margin: 1 1 4 1;
        }
        
        & Horizontal {
            height: auto;
            width: 100%;
        }

        & Input {
            height: auto;
            width: 1fr;
        }

        #svalue {
            width: 11;
        }
        #sfilter {
            min-width: 17;
            max-width: 23
        }
    }
    """
    search_result: var[dict[SongID, Song]] = var({}, init=False)
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("shift+q", "random", "Request A Random Searched Song"),
        Binding("shift+r", "random_favorited", "Request A Random Favorited Song"),
        Binding("shift+f", "toggle_filter", "Toggle Favorite Filter"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.list_view = SongListView()
        self.default_songs: dict[SongID, Song] = {}
        self.client = ListenClient.get_instance()
        self.min_search_length = 3
        self.search_amount: int | None = None
        self.selection: Select[int] = Select(
            [("50", 50), ("100", 100), ("200", 200), ("inf", -1)], allow_blank=False, value=50, id="svalue"
        )
        self.filter: Select[bool] = Select([("Favorited Only", True)], allow_blank=True, id="sfilter")
        self.search_result_copy: list[SongID] = []

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Input(
                placeholder="Press Enter To Search...",
                validators=Function(lambda x: len(x) >= self.min_search_length),
            )
            yield self.selection
            yield self.filter
        yield Center(Label("50 Results Found", id="counter"))
        yield self.list_view

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in {"random", "random_favorited", "toggle_filter"}:
            return ListenClient.get_instance().logged_in
        return True

    def action_toggle_filter(self) -> None:
        if self.filter.is_blank():
            self.filter.set_options([("Favorited Only", True)])
        else:
            self.filter.clear()

    async def action_random(self) -> None:
        if len(self.search_result_copy) > 0:
            random = random_choice(self.search_result_copy)
            self.search_result_copy.remove(random)
        else:
            self.notify("No more songs to request!", severity="warning")
            return

        res: Song | RequestError = await self.client.request_song(random, exception_on_error=False)
        if isinstance(res, Song):
            title = res.format_title(romaji_first=Config.get_config().display.romaji_first)
            artist = res.format_artists(romaji_first=Config.get_config().display.romaji_first)
            self.notify(
                f"{title}" + f" by [red]{artist}[/]" if artist else "",
                title="Sent to queue",
            )
        elif res == RequestError.FULL:
            self.notify("All requests have been used up for today!", severity="warning")
        else:
            self.notify("No more songs to request!", severity="warning")

    async def action_random_favorited(self) -> None:
        res: Song | RequestError = await self.client.request_random_favorite(exception_on_error=False)
        romaji_first = Config.get_config().display.romaji_first
        if isinstance(res, Song):
            title = res.format_title(romaji_first=romaji_first)
            artist = res.format_artists(romaji_first=romaji_first)
            self.notify(
                f"{title}" + f" by [red]{artist}[/]" if artist else "",
                title="Sent to queue",
            )
        else:
            self.notify("All requests have been used up for today!", severity="warning")

    @work
    async def watch_search_result(self, new_value: dict[SongID, Song]) -> None:
        self.list_view.clear()
        favorited: dict[SongID, bool] = {}
        if self.client.logged_in:
            favorited = await self.client.check_favorite(new_value.keys())
        self.list_view.extend(
            ButtonSongItem(song, favorited=favorited.get(song.id, False)) for song in new_value.values()
        )
        self.query_one("#counter", Label).update(
            f"{len(new_value.keys())} Results Found" if len(new_value.keys()) > 0 else "No Result Found"
        )
        self.search_result_copy = [*new_value.keys()]
        self.list_view.loading = False

    @work
    async def on_mount(self) -> None:
        if not self.client.logged_in:
            self.filter.styles.display = "none"
        self.list_view.loading = True
        self.default_songs = self.to_dict(await self.client.songs(0, 50))
        self.search_result = self.default_songs

    @on(Select.Changed, "#svalue")
    def search_value_changed(self, event: Select.Changed) -> None:
        if event.value == -1:
            self.search_amount = None
        else:
            self.search_amount = int(event.value) if isinstance(event.value, int) else 50
            self.search()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.validation_result and event.validation_result.is_valid:
            self.search(True)
        else:
            return

    @on(Select.Changed, "#sfilter")
    @work
    async def search(self, valid: bool = False) -> None:
        inp = self.query_one(Input)
        search = inp.value
        if valid:
            self.list_view.loading = True
            self.search_result = self.to_dict(
                await self.client.search(search, self.search_amount, favorite_only=not self.filter.is_blank())
            )
            return
        validation = inp.validate(search)
        if validation and validation.is_valid:
            self.list_view.loading = True
            self.search_result = self.to_dict(
                await self.client.search(search, self.search_amount, favorite_only=not self.filter.is_blank())
            )

    @on(SongListView.SongSelected)
    async def song_selected(self, event: SongListView.SongSelected) -> None:
        self.app.push_screen(SongScreen(event.song.id))

    @on(SongListView.ArtistSelected)
    async def artist_selected(self, event: SongListView.ArtistSelected) -> None:
        self.app.push_screen(ArtistScreen(event.artist.id))

    def to_dict(self, songs: list[Song]) -> dict[SongID, Song]:
        return {song.id: song for song in songs}
