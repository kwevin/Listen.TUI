# pyright: reportUnknownMemberType=false, reportMissingTypeStubs=false
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta
from logging import getLogger
from typing import Any

import websockets.client as websockets
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.reactive import var
from textual.widget import Widget
from textual.widgets import Label
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

from listentui.data.config import Config
from listentui.listen.types import ListenWsData
from listentui.widgets.custom import DurationProgressBar, VanityBar
from listentui.widgets.mpvThread import MPVThread
from listentui.widgets.songContainer import SongContainer


class Player(Widget):
    DEFAULT_CSS = """
    Player {
        align: left middle;
        width: 1fr;
        height: 8;
        padding: 0 1;

        #debug {
            width: 100%;
            height: 1;
            align-horizontal: center;

            & Label {
                padding-left: 2;
            }
        
            #retries {
                color: red;
            }

        }
    }
    """

    retries: var[int] = var(0)

    class WebsocketUpdated(Message):
        def __init__(self, data: ListenWsData) -> None:
            super().__init__()
            self.data = data

    class WebsocketStatus(Message):
        def __init__(self, state: bool, last_heartbeat: datetime) -> None:
            super().__init__()
            self.is_alive = state
            self.last_heartbeat = last_heartbeat

    def __init__(self) -> None:
        super().__init__()
        self._log = getLogger(__name__)
        self.ws_data: ListenWsData | None = None
        self.progress_bar = DurationProgressBar(stop=True, pause_on_end=True)
        self.player = MPVThread(self)
        self.idle_lock = False
        self.soft_cap = 5
        self.websocket_time = 0
        self.mpv_time = 0
        self.start_time = time.time()
        self.mpv_cache: MPVThread.DemuxerCacheState | None = None
        self.can_update = True
        self.set_interval(1, self.update_time_elapsed)
        self.set_interval(1, self.update_cache)

    def compose(self) -> ComposeResult:
        yield SongContainer()
        yield self.progress_bar
        with Horizontal(id="debug"):
            yield Label(id="retries", classes="hidden")
            yield Label(id="heartbeat")
            yield Label(id="delay")
            yield Label(id="cache")
            yield Label(id="time")

    def on_mount(self) -> None:
        self.loading = True
        self.websocket()
        self.player.start()

        self.query_one("#delay", Label).tooltip = "Delay"
        self.query_one("#cache", Label).tooltip = "Cache"
        self.query_one("#time", Label).tooltip = "Uptime"

    def watch_retries(self, new_value: int) -> None:
        self._log.debug(f"retries = {new_value} / {self.soft_cap}")
        retries = self.query_one("#retries", Label)
        if new_value > 0:
            retries.update(f"{new_value}/{self.soft_cap}!")
            if new_value > self.soft_cap:
                retries.styles.color = "red"
            else:
                retries.styles.color = "yellow"
        else:
            retries.update("")

    def update_cache(self) -> None:
        if not self.player.cache:
            return
        self.query_one("#cache", Label).update(
            f"{self.player.cache.cache_duration:.2f}s/{self.player.cache.fw_byte / 1000:.0f}KB"
        )

    def update_delay(self) -> None:
        if self.mpv_time == 0 and self.websocket_time == 0:
            return
        if self.mpv_time == 0 or self.websocket_time == 0:
            self.query_one("#delay", Label).update("-s")
            return

        self.query_one("#delay", Label).update(f"{round(self.mpv_time - self.websocket_time)}s")
        self.mpv_time = 0
        self.websocket_time = 0

    def update_time_elapsed(self) -> None:
        self.query_one("#time", Label).update(f"{timedelta(seconds=round(time.time() - self.start_time))}")

    @on(WebsocketStatus)
    def update_heartbeat(self, status: WebsocketStatus) -> None:
        label = self.query_one("#heartbeat", Label)
        if status.is_alive:
            label.update("[green]OK[/]")
        else:
            label.update("[red]DEAD[/]")
        label.tooltip = f"Last: {status.last_heartbeat.strftime('%H:%M:%S')}"

    @on(WebsocketUpdated)
    def update_websocket_time(self, _: None) -> None:
        self.websocket_time = time.time()
        self.update_delay()

    @on(MPVThread.Started)
    def on_started(self) -> None:
        self.progress_bar.resume()

    @on(MPVThread.Metadata)
    def update_metadata(self, meta: MPVThread.Metadata) -> None:
        meta.stop()
        if self.retries == 0:
            self.mpv_time = time.time()
            self.update_delay()
        self.progress_bar.resume()
        self.can_update = True

    @on(MPVThread.CoreIdle)
    def on_idle(self, state: MPVThread.CoreIdle) -> None:
        state.stop()
        idle = state.state

        self._log.debug(f"{idle = }")

        if idle is False and self.idle_lock is True:
            self.retries = 0
            self.idle_lock = False
            self.workers.cancel_group(self, "MPV_Idle_Restarter")

        if idle is True and self.player.paused is False and self.idle_lock is False:
            self.idle_lock = True
            self._start_idle_restarter()

    @work(group="wait_update", exclusive=True)
    async def can_force_update(self, data: ListenWsData) -> None:
        start = time.time()
        max_wait_time = 8
        if data.song.duration != 0:
            while not self.can_update and time.time() - start < max_wait_time:
                await asyncio.sleep(0.1)
        else:
            self.progress_bar.resume()
        self.query_one(SongContainer).update_song(data.song)
        self.query_one(VanityBar).update_vanity(data)
        self.can_update = False

    @work(group="MPV_Idle_Restarter", exclusive=True, thread=True)
    async def _start_idle_restarter(self) -> None:
        count = 0
        timeout = Config.get_config().player.timeout_restart
        while count < timeout:
            count += 1
            await asyncio.sleep(1)

        while self.idle_lock is True:
            if self.retries < self.soft_cap:
                self.player.restart()
            else:
                self.player.hard_restart()

            self.retries += 1
            await asyncio.sleep(10)
        self.retries = 0

    @work(exclusive=True, group="websocket")
    async def websocket(self) -> None:
        last_heartbeat: datetime = datetime.now()
        async for self._ws in websockets.connect("wss://listen.moe/gateway_v2", ping_interval=None, ping_timeout=None):
            try:
                while True:
                    res: dict[str, Any] = json.loads(await self._ws.recv())
                    match res["op"]:
                        case 1:
                            self.ws_data = ListenWsData.from_data(res)
                            # self._log.info(pretty_repr(self.ws_data))
                            self.post_message(self.WebsocketUpdated(self.ws_data))
                            self.progress_bar.pause()
                            self.progress_bar.update_progress(self.ws_data.song)
                            self.can_force_update(self.ws_data)
                        case 0:
                            self.loading = False
                            self.post_message(self.WebsocketStatus(True, last_heartbeat))
                            self.keepalive = self.ws_keepalive(res["d"]["heartbeat"] / 1000)
                        case 10:
                            last_heartbeat = datetime.now()
                            self.post_message(self.WebsocketStatus(True, last_heartbeat))
                        case _:
                            pass
            except ConnectionClosedOK:
                return
            except ConnectionClosedError:
                self.post_message(self.WebsocketStatus(False, last_heartbeat))
                self._log.exception("Websocket Connection Closed Unexpectedly")
                self.keepalive.cancel()
                continue

    @work(exclusive=True, group="ws_keepalive")
    async def ws_keepalive(self, interval: int = 35) -> None:
        try:
            while True:
                await asyncio.sleep(interval)
                await self._ws.send(json.dumps({"op": 9}))
        except (ConnectionClosedOK, ConnectionError):
            return
