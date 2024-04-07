import webbrowser
from datetime import datetime
from typing import Any, ClassVar

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.coordinate import Coordinate
from textual.reactive import var
from textual.widgets import Label

from ..data.config import Config
from ..data.theme import Theme
from ..listen.client import ListenClient
from ..listen.types import PlayStatistics, SongID
from ..screen.modal import ConfirmScreen, SelectionScreen, SongScreen
from .base import BasePage
from .custom import ExtendedDataTable as DataTable
from .mpvplayer import MPVStreamPlayer


class HistoryPage(BasePage):
    DEFAULT_CSS = """
    HistoryPage DataTable {
        width: 1fr;
        height: 1fr;
    }
    HistoryPage DataTable > .datatable--cursor {
        text-style: bold underline;
    }
    HistoryPage > Label {
        padding: 0 0 1 1;
    }
    """
    BINDINGS: ClassVar[list[BindingType]] = [Binding("ctrl+r", "refresh", "Refresh")]

    history_result: var[dict[SongID, PlayStatistics]] = var({}, init=False)
    favorited: var[dict[SongID, bool]] = var({}, init=False)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.client = ListenClient.get_instance()

    def compose(self) -> ComposeResult:
        yield Label(f"Last Updated: {datetime.now().strftime('%H:%M:%S')}")
        yield DataTable()

    def on_focus(self) -> None:
        self.query_one(DataTable).focus()

    def search_song(self, song_id: SongID | int) -> PlayStatistics:
        return self.history_result[SongID(song_id)]

    def on_mount(self) -> None:
        data_table = self.query_one(DataTable)
        data_table.add_column("Id")
        data_table.add_column("Track", width=50)
        data_table.add_column("Requested By")
        data_table.add_column("Played At")
        data_table.add_column("Artists", width=40)
        data_table.add_column("Album")
        data_table.add_column("Source")
        self.update_history()

    @work(group="table")
    async def watch_history_result(self, histories: dict[SongID, PlayStatistics]) -> None:
        romaji_first = Config.get_config().display.romaji_first
        data_table = self.query_one(DataTable)
        data_table.clear()
        if self.client.logged_in:
            self.favorited = await self.client.check_favorite(list(histories))
        for history in histories.values():
            song = history.song
            row = [
                Text(str(song.id), style=f"{Theme.ACCENT}") if self.favorited.get(song.id) else Text(str(song.id)),
                self.ellipsis(song.format_title(romaji_first=romaji_first), 50),
                Text(str(history.requester.display_name), style=f"{Theme.ACCENT}") if history.requester else "",
                history.created_at.strftime("%d-%m-%Y %H:%M:%S"),
                self.ellipsis(song.format_artists(romaji_first=romaji_first), 40),
                song.format_album(romaji_first=romaji_first),
                song.format_source(romaji_first=romaji_first),
            ]
            data_table.add_row(*row)
        data_table.refresh(layout=True)

    @work(group="table")
    async def on_data_table_cell_selected(self, event: DataTable.CellSelected) -> None:
        data_table = self.query_one(DataTable)
        column = event.coordinate.column
        id_coord = Coordinate(event.coordinate.row, 0)
        _id: Text = data_table.get_cell_at(id_coord)
        song_id = SongID(int(_id.plain))
        song = self.search_song(song_id).song
        romaji_first = Config.get_config().display.romaji_first
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
            case 4:
                if song.artists:
                    if len(song.artists) == 1:
                        if await self.app.push_screen(ConfirmScreen(label="Open Artist Page?"), wait_for_dismiss=True):
                            webbrowser.open_new_tab(song.artists[0].link)
                    else:
                        options = song.format_artists_list()
                        if not options:
                            return
                        result = await self.app.push_screen(SelectionScreen(options), wait_for_dismiss=True)
                        if result is not None:
                            webbrowser.open_new_tab(song.artists[result].link)
            case 5:
                # pylance keep saying no overload for await push_screen
                if song.album and await self.app.push_screen(
                    ConfirmScreen(label="Open Album Page?"),
                    wait_for_dismiss=True,  # type: ignore
                ):
                    webbrowser.open_new_tab(song.album.link)
            case 6:
                if song.source and await self.app.push_screen(
                    ConfirmScreen(label="Open Source Page?"),
                    wait_for_dismiss=True,  # type: ignore
                ):
                    webbrowser.open_new_tab(song.source.link)
            case _:
                pass

    @work(exclusive=True, group="table-update")
    async def update_history(self) -> None:
        data_table = self.query_one(DataTable)
        amount = Config.get_config().display.history_amount
        data_table.loading = True
        history = await self.client.history(amount, 1)
        self.history_result = {history.song.id: history for history in history}
        data_table.loading = False

    def action_refresh(self) -> None:
        self.update_history()
        self.query_one(Label).update(f"Last Updated: {datetime.now().strftime('%H:%M:%S')}")

    @work(exclusive=True, group="table-update")
    async def update_one(self) -> None:
        data_table = self.query_one(DataTable)
        data_table.loading = True
        history = await self.client.history(1, 1)
        self.history_result = {history[0].song.id: history[0], **self.history_result}
        data_table.loading = False

    def ellipsis(self, text: str | None, max_length: int) -> str:
        if not text:
            return ""
        return text if len(text) <= max_length else text[: max_length - 1] + "…"
