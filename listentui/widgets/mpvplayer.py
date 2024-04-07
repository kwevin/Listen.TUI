# pyright: reportUnknownMemberType=false, reportMissingTypeStubs=false
import asyncio
from logging import DEBUG, INFO, WARNING
from typing import Any, Callable

import mpv
from textual import on, work
from textual.message import Message
from textual.reactive import var
from textual.widget import Widget
from textual.worker import Worker

from ..data import Config
from ..utilities import get_logger


class MPVStreamPlayer(Widget):
    DEFAULT_CSS = """ 
    MPVStreamPlayer {
        width: 100%;
        height: 100%;
    }
    """

    is_playing: var[bool] = var(True, init=False)
    volume: var[int] = var(100, init=False)

    class Timeout(Message):
        def __init__(self) -> None:
            super().__init__()

    class Restarted(Message):
        def __init__(self) -> None:
            super().__init__()

    def __init__(self) -> None:
        super().__init__()
        self._log = get_logger()
        self.stream_url = "https://listen.moe/stream"
        self.player = mpv.MPV(**self.get_options())
        self.pv_player: mpv.MPV | None = None
        self._idle_count = 0

    @property
    def idle_count(self) -> int:
        return self._idle_count

    @property
    def core_idle(self) -> bool:
        value = self._get_value("core_idle")
        return bool(value) if value else False

    @property
    def paused(self) -> bool:
        value = self._get_value("pause")
        return bool(value) if value else False

    def _get_value(self, value: str, *args: Any) -> Any | None:
        try:
            return getattr(self.player, value, *args)
        except (RuntimeError, mpv.ShutdownError):
            return None

    def get_options(self) -> dict[str, Any]:
        mpv_options = Config.get_config().player.mpv_options.copy()
        mpv_options["volume"] = Config.get_config().persistant.volume
        if self.volume == 0:
            mpv_options["volume"] = 0
        if Config.get_config().player.dynamic_range_compression and not mpv_options.get("af"):
            mpv_options["af"] = "acompressor=ratio=4,loudnorm=I=-16:LRA=11:TP=-1.5"

        return mpv_options

    def on_mount(self) -> None:
        self.init_player()

    def on_unmount(self) -> None:
        Config.get_config().save()
        self.player.terminate()

    @work(group="player", thread=True)
    async def init_player(self) -> None:
        self.loading = True
        self.app.call_from_thread(self.reset)
        self.loading = False
        self.styles.display = "none"

    @work(group="player")
    async def watch_is_playing(self, new: bool) -> None:
        if new:
            self.player.pause = False
            self.reset()
        else:
            self.player.pause = True

    def watch_volume(self, new: int) -> None:
        self.player.volume = new

    @work(exclusive=True, group="player_reset", thread=True)
    def reset(self) -> None:
        self.post_message(self.Timeout())
        self.player.play(self.stream_url)
        self.player.wait_until_playing()
        self.post_message(self.Restarted())

    @work(group="player")
    async def hard_restart(self) -> None:
        self.player.terminate()
        self.player = mpv.MPV(**self.get_options())
        self.reset()

    @work(exclusive=True, group="player_restarter")
    async def restarter(self) -> None:
        timeout = Config.get_config().player.timeout_restart

        while True:
            if self.core_idle and not self.paused:
                if self._idle_count > timeout:
                    self._log.debug(f"Player timeout exceed: {timeout}s")
                    self.hard_restart()
                else:
                    self._idle_count += 1
                    self._log.debug(
                        f"idle: {self.core_idle} | paused: {self.paused} | timeout: {self._idle_count}/{timeout}"
                    )
            else:
                self._idle_count = 0

            await asyncio.sleep(1)
            # if self.core_idle and not self.paused:
            #     self._log.debug(f"idle: {self.core_idle} | paused: {self.paused} | timeout: {counter}/{timeout}")
            #     counter += 1
            # else:
            #     counter = 0
            # if counter == timeout:
            #     self.hard_restart()
            #     self._log.debug(f"Player timeout exceed: {timeout}s")
            # await asyncio.sleep(1)

    def log_handler(self, loglevel: str, component: str, message: str):
        if component == "display-tags":
            return
        match loglevel:
            case "info":
                level = INFO
            case "warn":
                level = WARNING
            case "debug":
                level = DEBUG
            case _:
                level = DEBUG
        self._log.log(level=level, msg=f"[{component}] {message}")

    @on(Timeout)
    def on_timeout(self, event: Timeout):
        self.workers.cancel_group(self, "player_restarter")

    @on(Restarted)
    def on_restarted(self, event: Restarted):
        self.restart_worker = self.restarter()

    @work(exclusive=True, thread=True, group="preview")
    def preview(
        self,
        song_url: str,
        on_play: Callable[[Worker[Any]], Any],
        on_error: Callable[[Worker[Any]], Any],
        on_finish: Callable[[Worker[Any]], Any] | None = None,
    ) -> None:
        """
        Args:
            song_url (str): The song url to play
            on_play (Worker[Any]): The callback to run when the song starts playing
            on_error (Worker[Any]): The callback to run when the song fails to play
        """
        final_url = f"https://cdn.listen.moe/snippets/{song_url}".strip()
        self.pv_player = mpv.MPV(log_handler=self.log_handler, **self.get_options())

        @self.pv_player.event_callback("end-file")
        def check(event: mpv.MpvEvent):  # type: ignore
            if isinstance(event.data, mpv.MpvEventEndFile) and event.data.reason == mpv.MpvEventEndFile.ERROR:
                self.app.call_from_thread(on_error)
                self.pv_player.terminate()  # type: ignore

        try:
            self.pv_player.play(final_url)
            self.pv_player.wait_until_playing()
            self.is_playing = False
            self.app.call_from_thread(on_play)
            self.pv_player.wait_for_playback()
        except mpv.ShutdownError:
            self.app.call_from_thread(on_error)
        finally:
            self.pv_player.terminate()
            if on_finish:
                self.app.call_from_thread(on_finish)
        self.is_playing = True

    def terminate_preview(self) -> None:
        if not self.pv_player:
            return
        self.pv_player.terminate()
