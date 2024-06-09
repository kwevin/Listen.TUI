# import webbrowser
from random import choice as random_choice
from typing import Any, ClassVar

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal
from textual.coordinate import Coordinate
from textual.reactive import var
from textual.validation import Function
from textual.widgets import Input, Select

from listentui.data import Config, Theme
from listentui.listen.client import ListenClient, RequestError
from listentui.listen.types import Song, SongID
from listentui.screen import AlbumScreen, ArtistScreen, ConfirmScreen, SelectionScreen, SongScreen, SourceScreen
from listentui.widgets.base import BasePage
from listentui.widgets.custom import ExtendedDataTable as DataTable
from listentui.widgets.custom import StaticButton, ToggleButton
from listentui.widgets.mpvplayer import MPVStreamPlayer


class FavoriteButton(ToggleButton):
    def __init__(self):
        super().__init__("Toggle Favorite Only", "Favorited Only", check_user=True)


class RandomSongButton(StaticButton):
    def __init__(self):
        super().__init__("Request A Random Song", check_user=True, id="random_song")


class RandomFavoriteButton(StaticButton):
    def __init__(self):
        super().__init__("Request A Random Favorited Song", check_user=True, id="random_favorite")


class SearchPage(BasePage):
    DEFAULT_CSS = """
    SearchPage Input {
        width: 1fr;
        height: auto;
    }
    SearchPage Horizontal {
        height: auto;
        width: 100%;
    }
    SearchPage Button {
        margin-left: 1;
    }
    SearchPage DataTable {
        width: 1fr;
        height: 1fr;
    }
    SearchPage Select {
        width: 12;
    }
    SearchPage DataTable > .datatable--cursor {
        text-style: bold underline;
    }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+l", "focus_input", "Focus Input"),
        Binding("ctrl+t", "toggle_favorite", "Toggle Favorite Only"),
        Binding("ctrl+n", "request_random", "Request Random Song"),
    ]
    search_result: var[dict[SongID, Song]] = var({}, init=False)
    favorited: var[dict[SongID, bool]] = var({}, init=False)
    favorites_only: var[bool] = var(False, init=False)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._defaults: dict[SongID, Song] = {}
        self._search_list: list[SongID] = []
        self.client = ListenClient.get_instance()
        self.min_search_length = 3
        self.search_amount: int | None = 50
        self.artist_max_width = 55
        self.title_max_width = 50
        self.selection: Select[int] = Select(
            [("50", 50), ("100", 100), ("200", 200), ("inf", -1)], allow_blank=False, value=50
        )

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Input(
                placeholder="Type Any Characters To Search...",
                validators=Function(lambda x: len(x) >= self.min_search_length),
            )
            yield self.selection
        with Horizontal():
            yield FavoriteButton()
            yield RandomSongButton()
            yield RandomFavoriteButton()
        yield DataTable()

    def on_focus(self) -> None:
        self.query_one(Input).focus()

    def search_song(self, song_id: SongID | int) -> Song:
        return self.search_result[SongID(song_id)]

    def to_dict(self, songs: list[Song]) -> dict[SongID, Song]:
        return {song.id: song for song in songs}

    @work(group="table")
    async def on_mount(self) -> None:
        data_table = self.query_one(DataTable)
        data_table.add_column("Id")
        data_table.add_column("Track", width=self.title_max_width)
        data_table.add_column("Artists", width=self.artist_max_width)
        data_table.add_column("Album")
        data_table.add_column("Source")
        self._defaults = self.to_dict(await self.client.songs(0, 50))
        self.search_result = self._defaults

    @work(exclusive=True, group="search", exit_on_error=False)
    async def watch_favorites_only(self, value: bool) -> None:
        search_term = self.query_one(Input).value
        if len(search_term) < self.min_search_length:
            return
        self.query_one(DataTable).loading = True
        self.search_result = self.to_dict(
            await self.client.search(search_term, self.search_amount, favorite_only=value)
        )
        self.query_one(DataTable).loading = False

    @work(group="table")
    async def watch_search_result(self, result: dict[SongID, Song]) -> None:
        self._search_list = list(result)
        romaji_first = Config.get_config().display.romaji_first
        data_table = self.query_one(DataTable)
        data_table.clear()
        if len(result) == 0:
            return
        if self.client.logged_in:
            self.favorited = await self.client.check_favorite(list(result))
        for song in result.values():
            row = [
                Text(str(song.id), style=f"{Theme.ACCENT}") if self.favorited.get(song.id) else Text(str(song.id)),
                self.ellipsis(song.format_title(romaji_first=romaji_first), self.title_max_width),
                self.ellipsis(song.format_artists(romaji_first=romaji_first), self.artist_max_width),
                song.format_album(romaji_first=romaji_first),
                song.format_source(romaji_first=romaji_first),
            ]
            data_table.add_row(*row)

    @work(group="table")
    async def on_data_table_cell_selected(self, event: DataTable.CellSelected) -> None:  # noqa: PLR0911, PLR0914
        data_table = self.query_one(DataTable)
        column = event.coordinate.column
        id_coord = Coordinate(event.coordinate.row, 0)
        _id: Text = data_table.get_cell_at(id_coord)
        song_id = SongID(int(_id.plain))
        song = self.search_song(song_id)
        romaji_first = Config.get_config().display.romaji_first
        client = ListenClient.get_instance()
        match column:
            case 0:
                if not self.client.logged_in:
                    return
                state: bool = self.favorited.get(song_id, False)
                if await self.app.push_screen(
                    ConfirmScreen(label=f"{'Unfavorite' if state else 'Favorite'} Song?"), wait_for_dismiss=True
                ):
                    await self.client.favorite_song(song_id)
                    data_table.update_cell_at(
                        id_coord, Text(str(song_id), style=f"{Theme.ACCENT}") if not state else Text(str(song_id))
                    )
                    self.notify(
                        f"{'Unfavorited' if state else 'Favorited'} "
                        + f"{song.format_title(romaji_first=romaji_first)}"
                    )
                    self.favorited[song_id] = not state
            case 1:
                favorited_state = await self.app.push_screen(
                    SongScreen(song, self.app.query_one(MPVStreamPlayer), self.favorited.get(song_id, False)),
                    wait_for_dismiss=True,
                )
                self.favorited[song_id] = favorited_state
                data_table.update_cell_at(
                    id_coord,
                    Text(str(song_id), style=f"{Theme.ACCENT}") if favorited_state else Text(str(song_id)),
                )
            case 2:
                if not song.artists:
                    return

                player = self.app.query_one(MPVStreamPlayer)
                if len(song.artists) == 1:
                    artist = await client.artist(song.artists[0].id)
                    if not artist:
                        return
                    self.app.push_screen(ArtistScreen(artist, player))
                else:
                    options = song.format_artists_list(romaji_first=romaji_first)
                    if not options:
                        return
                    result = await self.app.push_screen(SelectionScreen(options), wait_for_dismiss=True)
                    if result is not None:
                        artist = await client.artist(song.artists[result].id)
                        if not artist:
                            return
                        self.app.push_screen(ArtistScreen(artist, player))
            case 3:
                if song.album:
                    album = await client.album(song.album.id)
                    if not album:
                        return
                    self.app.push_screen(AlbumScreen(album, self.app.query_one(MPVStreamPlayer)))
            case 4:
                if song.source:
                    source = await client.source(song.source.id)
                    if not source:
                        return
                    self.app.push_screen(SourceScreen(source, self.app.query_one(MPVStreamPlayer)))
            case _:
                pass

    def on_input_submitted(self) -> None:
        self.query_one(DataTable).focus()

    @work(exclusive=True, group="search", exit_on_error=False)
    async def on_input_changed(self, event: Input.Changed) -> None:
        if event.validation_result and event.validation_result.is_valid:
            self.query_one(DataTable).loading = True
            self.search_result = self.to_dict(
                await self.client.search(event.value, self.search_amount, favorite_only=self.favorites_only)
            )
            self.query_one(DataTable).loading = False
        else:
            self.search_result = self._defaults

    def action_focus_input(self) -> None:
        self.query_one(Input).focus()

    def action_toggle_favorite(self) -> None:
        if self.client.logged_in:
            self.favorites_only = not self.favorites_only
            self.query_one(FavoriteButton).set_toggle_state(self.favorites_only)
        else:
            self.notify("Must be logged in to toggle favorite only", severity="warning")

    @on(FavoriteButton.Toggled)
    def toggle_favorite(self, event: FavoriteButton.Toggled) -> None:
        self.favorites_only = event.state

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.value == -1:
            self.search_amount = None
        else:
            self.search_amount = int(event.value) if isinstance(event.value, int) else 20

    @on(RandomSongButton.Pressed, "RandomSongButton")
    async def request_random(self) -> None:
        if len(self._search_list) > 0:
            random = random_choice(self._search_list)
            self._search_list.remove(random)
        else:
            self.notify("No more songs to request!", severity="warning")
            return

        res: Song | RequestError = await self.client.request_song(random, exception_on_error=False)
        if isinstance(res, Song):
            title = res.format_title(romaji_first=Config.get_config().display.romaji_first)
            artist = res.format_artists(romaji_first=Config.get_config().display.romaji_first)
            self.notify(
                f"{title}" + f" by [{Theme.ACCENT}]{artist}[/]" if artist else "",
                title="Sent to queue",
            )
        elif res == RequestError.FULL:
            self.notify("All requests have been used up for today!", severity="warning")
        else:
            self.notify("No more songs to request!", severity="warning")

    @on(RandomFavoriteButton.Pressed, "RandomFavoriteButton")
    async def request_random_favorite(self) -> None:
        res: Song | RequestError = await self.client.request_random_favorite(exception_on_error=False)
        romaji_first = Config.get_config().display.romaji_first
        if isinstance(res, Song):
            title = res.format_title(romaji_first=romaji_first)
            artist = res.format_artists(romaji_first=romaji_first)
            self.notify(
                f"{title}" + f" by [{Theme.ACCENT}]{artist}[/]" if artist else "",
                title="Sent to queue",
            )
        else:
            self.notify("All requests have been used up for today!", severity="warning")

    def ellipsis(self, text: str | None, max_length: int) -> str:
        if not text:
            return ""
        return text if len(text) <= max_length else text[: max_length - 3] + "..."
