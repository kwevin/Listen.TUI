import asyncio
import json
import time

# from datetime import datetime, timezone
from logging import getLogger
from typing import Any, Optional

import websockets.client as websockets
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

from ..data import Config, Theme
from ..listen import ListenClient
from ..listen.types import ListenWsData, Song
from ..screen.modal import ArtistScreen, SourceScreen
from .custom import DurationProgressBar, ScrollableLabel
from .mpvplayer import MPVStreamPlayer


class SongContainer(Widget):
    DEFAULT_CSS = """
    SongContainer {
        width: 1fr;
        height: auto;
    }
    SongContainer #artist {
        color: rgb(249, 38, 114);
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
        self.query_one("#artist", ScrollableLabel).update(*[Text.from_markup(artist) for artist in self.artist])
        self.query_one("#title", ScrollableLabel).update(Text.from_markup(f"{self.title}"))
        if self.source:
            self.query_one("#title", ScrollableLabel).append(Text.from_markup(f"[cyan]\\[{self.source}][/cyan]"))

    def compose(self) -> ComposeResult:
        yield ScrollableLabel(id="artist")
        yield ScrollableLabel(id="title", sep=" ")

    async def on_scrollable_label_clicked(self, event: ScrollableLabel.Clicked) -> None:
        if not self.song:
            return
        player = self.app.query_one(MPVStreamPlayer)
        client = ListenClient.get_instance()
        if event.widget.id == "artist":
            if not self.song.artists:
                return
            artist_id = self.song.artists[event.index].id
            self.notify(f"Fetching data for {event.content.plain}...")
            artist = await client.artist(artist_id)
            if not artist:
                return
            self.app.push_screen(ArtistScreen(artist, player))
        elif event.widget.id == "title":
            if event.index != 1:
                return
            if not self.song.source:
                return
            source_id = self.song.source.id
            self.notify(f"Fetching data for {event.content.plain}...")
            source = await client.source(source_id)
            if not source:
                return
            self.app.push_screen(SourceScreen(source, player))

    def set_tooltips(self, string: str | None) -> None:
        self.query_one("#title", ScrollableLabel).tooltip = string


class ListenWebsocket(Widget):
    DEFAULT_CSS = f"""
    ListenWebsocket {{
        align: left middle;
        height: 5;
        padding: 1 1 1 2;
        background: {Theme.BUTTON_BACKGROUND};
    }}
    """

    class Updated(Message):
        def __init__(self, data: ListenWsData) -> None:
            super().__init__()
            self.data = data

    class ConnectionClosed(Message):
        def __init__(self) -> None:
            super().__init__()

    def __init__(self) -> None:
        super().__init__()
        self._data: ListenWsData | None = None
        self._ws_data: dict[str, Any] = {}
        self._log = getLogger(__name__)

    @property
    def data(self):
        return self._data

    def compose(self) -> ComposeResult:
        yield SongContainer()
        yield DurationProgressBar()

    def on_mount(self) -> None:
        self.loading = True
        self.websocket()

    @work(exclusive=True, group="websocket")
    async def websocket(self) -> None:
        async for self._ws in websockets.connect("wss://listen.moe/gateway_v2", ping_interval=None, ping_timeout=None):
            try:
                while True:
                    self._ws_data: dict[str, Any] = json.loads(await self._ws.recv())
                    match self._ws_data["op"]:
                        case 1:
                            self._data = ListenWsData.from_data(self._ws_data)
                            self.query_one(DurationProgressBar).update_progress(self._data.song)
                            self.post_message(self.Updated(self._data))
                            self.query_one(SongContainer).song = self._data.song
                        case 0:
                            self.loading = False
                            self.keepalive = self.ws_keepalive(self._ws_data["d"]["heartbeat"] / 1000)
                        case 10:
                            self._last_heartbeat = time.time()
                        case _:
                            pass
            except ConnectionClosedOK:
                return
            except ConnectionClosedError:
                self._log.exception("Websocket Connection Closed Unexpectedly")
                self.keepalive.cancel()
                self.post_message(self.ConnectionClosed())
                continue

    @work(exclusive=True, group="ws_keepalive")
    async def ws_keepalive(self, interval: int = 35) -> None:
        try:
            while True:
                await asyncio.sleep(interval)
                await self._ws.send(json.dumps({"op": 9}))
        except (ConnectionClosedOK, ConnectionError):
            return
