from datetime import datetime, timedelta
from typing import ClassVar, Sequence

from rich.style import Style
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal
from textual.coordinate import Coordinate
from textual.fuzzy import Matcher
from textual.reactive import var
from textual.types import NoSelection
from textual.widgets import DataTable, Input, Label, Select
from textual.widgets.data_table import RowKey

from listentui.data.theme import Theme
from listentui.listen import ListenClient, PlayStatistics, SongID
from listentui.listen.interface import Song
from listentui.pages.base import BasePage
from listentui.screen.modal import (
    AlbumScreen,
    ArtistScreen,
    SelectionScreen,
    SongScreen,
    SourceScreen,
)
from listentui.utilities import de_kuten, format_time_since


class MarkupMatcher(Matcher):
    def highlight(self, candidate: str) -> Text:
        """Highlight the candidate with the fuzzy match.

        Args:
            candidate: The candidate string to match against the query.

        Returns:
            A [rich.text.Text][`Text`] object with highlighted matches.
        """
        text = Text.from_markup(candidate)
        match = self._query_regex.search(text.plain)
        if match is None:
            return text
        assert match.lastindex is not None
        offsets = [match.span(group_no)[0] for group_no in range(1, match.lastindex + 1)]
        for offset in offsets:
            text.stylize(self._match_style, offset, offset + 1)

        return text

    def highlights(self, candidate: list[str | Text]) -> list[Text]:
        highlighted: list[Text] = []
        for string in candidate:
            if isinstance(string, str):
                highlighted.append(self.highlight(string))
            else:
                highlighted.append(self.highlight(string.markup))

        return highlighted


class HistoryPage(BasePage):
    DEFAULT_CSS = """
    HistoryPage DataTable {
        width: 1fr;
        height: 1fr;
    }
    HistoryPage > Label {
        padding: 0 0 1 1;
    }
    HistoryPage Horizontal {
        width: 100%;
        height: auto;
    }
    HistoryPage Input {
        width: 1fr;
    }
    HistoryPage Select {
        width: 25
    }
    """
    BINDINGS: ClassVar[list[BindingType]] = [Binding("ctrl+r", "refresh", "Refresh")]

    history_result: var[list[PlayStatistics]] = var([], init=False, always_update=True)

    def __init__(self) -> None:
        super().__init__()
        self.client = ListenClient.get_instance()
        self.favorited: dict[SongID, bool] = {}
        self.table_lookup: dict[RowKey, PlayStatistics] = {}
        self.table: DataTable[str | Text | None] = DataTable(zebra_stripes=True)
        self.last_pos = 0
        self.input = Input(placeholder="Search to filter")
        self.last_updated_time = datetime.now()
        self.time_filter: Select[int] = Select(
            [("10mins", 10), ("30mins", 30), ("1hr", 60), ("2hr", 120), ("6hr", 360), ("12hr", 720), ("1day", 1440)],
            prompt="Filter by Time",
        )

        self.table.add_column("Id")
        self.table.add_column("Track", width=30)
        self.table.add_column("Requested By")
        self.table.add_column("Played At")
        self.table.add_column("Artists", width=30)
        self.table.add_column("Album", width=30)
        self.table.add_column("Source", width=30)

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield self.input
            yield self.time_filter
        yield Label(f"Last Updated: {format_time_since(self.last_updated_time)}")
        yield self.table

    @work
    async def watch_history_result(self, new_value: list[PlayStatistics]) -> None:
        if self.client.logged_in:
            not_found = [his.song.id for his in new_value if self.favorited.get(his.song.id) is None]
            self.favorited.update(dict.fromkeys(not_found, False))
            self.favorited.update(await self.client.check_favorite(not_found))

        self.last_updated_time = datetime.now()
        self.update_time_since()
        self.populate_table()

    def on_show(self) -> None:
        self.update_time_since()
        self.action_refresh()

    def update_time_since(self) -> None:
        self.query_one(Label).update(f"Last Updated: {format_time_since(self.last_updated_time)}")

    @work
    async def populate_table(self) -> None:
        self.table.clear()
        self.table_lookup = {}

        now = datetime.now()

        for history in self.history_result:
            sid = history.song.id
            song = history.song
            rows: Sequence[str | Text] = [
                Text(str(sid), style=f"{Theme.ACCENT}") if self.favorited.get(song.id) else Text(str(song.id)),
                de_kuten(song.format_title() or ""),
                Text(de_kuten(history.requester.display_name), style=f"{Theme.ACCENT}") if history.requester else "",
                history.created_at.strftime("%d-%m-%Y %H:%M:%S"),
                de_kuten(song.format_artists() or ""),
                de_kuten(song.format_album() or ""),
                de_kuten(song.format_source() or ""),
            ]

            # filter by time
            if not isinstance(self.time_filter.value, NoSelection) and history.created_at < now - timedelta(
                minutes=self.time_filter.value
            ):
                continue
            # filter by search_string
            if self.input.value:
                search_string = self.input.value
                threshold = 0.7
                matcher = MarkupMatcher(search_string, match_style=Style(color="yellow"))

                if not any(matcher.match(str(row)) > threshold for row in rows):
                    continue

                rows = matcher.highlights(rows)

            key = self.table.add_row(*rows, height=None)
            self.table_lookup[key] = history

        if not self.input.value and self.time_filter.is_blank():
            self.table.add_rows(["", ""])
            self.table.add_row("", "", "", "Load More", "", "", "")
            self.table.move_cursor(row=self.last_pos, column=0)

    def on_input_changed(self, event: Input.Changed) -> None:
        self.populate_table()

    @work
    async def on_select_changed(self, event: Select.Changed) -> None:
        if (datetime.now() - self.last_updated_time) > timedelta(minutes=10):
            self.last_pos = 0
            self.history_result = await self.client.history(offset=1)
        self.populate_table()

    @work
    async def action_refresh(self) -> None:
        self.last_pos = 0
        self.history_result = await self.client.history(offset=1)

    def on_data_table_cell_selected(self, cell: DataTable.CellSelected):
        if not cell.value:
            return
        if cell.value == "Load More":
            self.load_additional(cell.coordinate.row - 3)
        else:
            rowkey = cell.cell_key.row_key
            match cell.coordinate.column:
                case 0:
                    self.favorite(rowkey, cell.coordinate)
                case 1:
                    self.show_song(rowkey, cell.coordinate)
                case 4:
                    self.select_and_show_artist(rowkey)
                case 5:
                    self.show_album(rowkey)
                case 6:
                    self.show_source(rowkey)
                case _:
                    return

    @work
    async def load_additional(self, at: int = 0) -> None:
        self.history_result.extend(await self.client.history(50, len(self.history_result) + 1))
        self.last_pos = at
        self.history_result = self.history_result

    @work
    async def favorite(self, rowkey: RowKey, coordinate: Coordinate) -> None:
        if not self.client.logged_in:
            return

        song = self.get_song(rowkey)
        state = not self.favorited[song.id]
        self.favorited[song.id] = state
        await self.client.favorite_song(song.id)

        new_value = Text(str(song.id), style=f"{Theme.ACCENT}") if state else Text(str(song.id))
        self.table.update_cell_at(coordinate, new_value)
        self.notify(f"{'Favorited' if state else 'Unfavorited'} " + f"{song.format_title()}")

    @work
    async def show_song(self, rowkey: RowKey, coordinate: Coordinate) -> None:
        song = self.get_song(rowkey)
        current = self.favorited[song.id]
        res = await self.app.push_screen_wait(SongScreen(song.id, current))

        if res is not current:
            self.favorited[song.id] = res
            new_value = Text(str(song.id), style=f"{Theme.ACCENT}") if res else Text(str(song.id))
            self.table.update_cell_at(coordinate.left(), new_value)

    @work
    async def select_and_show_artist(self, rowkey: RowKey) -> None:
        song = self.get_song(rowkey)
        if not song.artists:
            return

        if len(song.artists) == 1:
            self.app.push_screen(ArtistScreen(song.artists[0].id))
        else:
            options = song.format_artists_list()
            if not options:
                return
            result = await self.app.push_screen_wait(SelectionScreen(options))
            if result is not None:
                self.app.push_screen(ArtistScreen(song.artists[result].id))

    def show_album(self, rowkey: RowKey) -> None:
        song = self.get_song(rowkey)
        if not song.album:
            return
        self.app.push_screen(AlbumScreen(song.album.id))

    def show_source(self, rowkey: RowKey) -> None:
        song = self.get_song(rowkey)
        if not song.source:
            return
        self.app.push_screen(SourceScreen(song.source.id))

    def get_song(self, rowkey: RowKey) -> Song:
        return self.table_lookup[rowkey].song

    # @work
    # async def add_to_history(self, _) -> None:
    #     res = await self.client.history(1, 1)
    #     latest = res[0]
    #     history: dict[SongID, PlayStatistics] = {}
    #     history[latest.song.id] = latest
    #     history.update(self.history_result)
    #     self.history_result = history
