# pyright: reportUnknownMemberType=false, reportMissingTypeStubs=false
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from logging import DEBUG, INFO, WARNING, getLogger
from threading import Lock, Thread
from time import sleep
from typing import Any, Self, Type

from mpv import MPV, MpvEvent, MpvEventEndFile, ShutdownError
from rich.repr import RichReprResult
from textual.message import Message
from textual.widget import Widget

from listentui.data.config import Config


class MPVWatcher(Thread):
    def __init__(self, thread: MPVThread) -> None:
        super().__init__(name="MPVWatcher", daemon=True)
        self._log = getLogger(__name__)
        self.is_terminated = False
        self.player = thread
        self.base_timeout = 20
        self.retries = 0
        self.soft_retry_cap = 5
        self.hard_retry_cap = 10
        self.timeout_cap = 60

    def run(self) -> None:
        while True:
            if not self.is_player_alive():
                self._log.debug("Player is not alive, idling...")
                sleep(1)
                continue
            if self.is_not_playing():
                self.dispatch_restart()
                continue
            sleep(5)
            continue

    def is_player_alive(self) -> bool:
        return self.player.player.core_shutdown

    def is_not_playing(self) -> bool:
        return bool(self.player.core_idle is True and self.player.paused is False)

    def dispatch_restart(self) -> None:
        timeout = min(self.base_timeout + 5 * self.retries, self.timeout_cap)

        self._log.debug(
            f"Attempting restart: {self.retries}/{self.soft_retry_cap} max: {self.hard_retry_cap} current timeout: {timeout}"  # noqa: E501
        )

        if self.retries >= self.hard_retry_cap:
            self.player.main.post_message(self.player.Fail())
            return

        try:
            if self.retries > self.soft_retry_cap:
                self.player.hard_restart(timeout)
            else:
                self.player.restart(timeout)

            self._log.debug("Player sucessfully restarted")
            self.retries = 0
            self.player.main.post_message(self.player.SuccessfulRestart())
        except TimeoutError:
            self.retries += 1
            self.player.main.post_message(
                self.player.FailedRestart(self.retries, timeout, self.soft_retry_cap, self.hard_retry_cap)
            )


class MPVThread(Thread):
    instance: MPVThread | None = None

    def __init__(self, main: Widget) -> None:
        super().__init__(name="MPVThread", daemon=True)
        self.main = main
        self.stream_url = "https://listen.moe/stream"
        self.player = MPV(ytdl=True, **self.get_options(), log_handler=self.log_handler)
        self.watcher = MPVWatcher(self)
        self.muted_volume = 0
        self.pv_player: MPV | None = None
        self.cache: MPVThread.DemuxerCacheState | None = None
        self._metadata: MPVThread.Metadata | None = None
        self._log = getLogger(__name__)
        self._idle_count = 0
        self._pv_lock = Lock()
        self._lock = Lock()

    class Started(Message):
        def __init__(self) -> None:
            super().__init__()

    @dataclass
    class FailedRestart(Message):
        retry_no: int
        timeout: int
        soft_cap: int
        hard_cap: int

    class SuccessfulRestart(Message):
        def __init__(self) -> None:
            super().__init__()

    class Fail(Message):
        def __init__(self) -> None:
            super().__init__()

    @dataclass
    class DemuxerCacheState(Message):
        """
        For more information, see https://mpv.io/manual/master/#command-interface-demuxer-cache-state
        """

        cache_end: float
        """`cache_end`: total demuxer cache time (seconds)"""
        cache_duration: float
        """`cache_duration`: amount of cache (seconds)"""
        fw_byte: int
        """`fw_byte`: no. bytes buffered size from current decoding pos"""
        total_bytes: int
        """`total_bytes`: sum of cached seekable range"""
        seekable_start: float
        """`seekable_start`: approx timestamp of start of buffered range"""
        seekable_end: float | None
        """`seekable_end`: approx timestamp of end of buffered range"""

        @classmethod
        def from_cache_state(cls: Type[Self], data: dict[str, Any]) -> Self:
            cache_end = float(data.get("cache-end", -1))
            cache_duration = float(data.get("cache-duration", -1))
            fw_byte = int(data.get("fw-bytes", -1))
            total_bytes = int(data.get("total-bytes", -1))
            seekable_start = float(data.get("reader-pts", -1))
            seekable_ranges = data.get("seekable-ranges")
            seekable_end = float(seekable_ranges[0].get("end", -1)) if seekable_ranges else None

            return cls(cache_end, cache_duration, fw_byte, total_bytes, seekable_start, seekable_end)

    @dataclass
    class Metadata(Message):
        start: datetime
        track: str | None
        genre: str | None
        title: str | None
        artist: str | None
        year: str | None
        date: str | None
        album: str | None
        comment: str | None
        _ENCODER: str
        _icy_br: str
        _icy_genre: str
        _icy_name: str
        _icy_pub: str
        _icy_url: str

        def __rich_repr__(self) -> RichReprResult:
            yield self.start
            yield self.track
            yield self.title
            yield self.artist
            yield self.album

    class PreviewType(Enum):
        UNABLE = 1
        ERROR = 2
        LOCKED = 3
        PLAYING = 4
        FINISHED = 5

    class PreviewStatus(Message):
        def __init__(self, state: MPVThread.PreviewType, other: Any = None) -> None:
            super().__init__()
            self.state = state
            self.other = other

    @property
    def paused(self) -> bool | None:
        return bool(self._get_value("pause"))

    @paused.setter
    def paused(self, state: bool):
        self.player.pause = state

    @property
    def core_idle(self) -> bool:
        return bool(self._get_value("core_idle"))

    @property
    def volume(self) -> int:
        volume = self._get_value("volume")
        if not volume:
            return 0
        return int(volume)

    @volume.setter
    def volume(self, volume: int):
        self.player.volume = volume

    @property
    def ao_volume(self) -> float:
        ao_volume = self._get_value("ao_volume")
        if not ao_volume:
            return 0
        return float(ao_volume)

    @ao_volume.setter
    def ao_volume(self, volume: int):
        self.player.ao_volume = volume

    def _get_value(self, value: str, *args: Any) -> Any | None:
        try:
            return getattr(self.player, value, *args)
        except (RuntimeError, ShutdownError):
            return None

    # def _watch_core_idle(self, _: bool, new_value: bool | None) -> None:
    #     if new_value is None:
    #         self._log.debug("Unable to determine player idle status")
    #     self.main.post_message(self.CoreIdle(new_value or False))

    def _watch_metadata(self, _: dict[str, Any], new_value: dict[str, Any] | None) -> None:
        if new_value is None:
            return
        metadata = self.Metadata(
            start=datetime.now(timezone.utc),
            track=new_value.get("track"),
            genre=new_value.get("genre"),
            title=new_value.get("title"),
            artist=new_value.get("artist"),
            year=new_value.get("year"),
            date=new_value.get("date"),
            album=new_value.get("album"),
            comment=new_value.get("comment"),
            _ENCODER=new_value["ENCODER"],
            _icy_br=new_value["icy-br"],
            _icy_genre=new_value["icy-genre"],
            _icy_name=new_value["icy-name"],
            _icy_pub=new_value["icy-pub"],
            _icy_url=new_value["icy-url"],
        )
        if self._metadata == metadata:
            return
        self._metadata = metadata
        self._log.debug(new_value)
        self.main.post_message(metadata)

    def _watch_cache(self, _: dict[str, Any], new_value: dict[str, Any] | None) -> None:
        if new_value is None:
            return
        self.cache = self.DemuxerCacheState.from_cache_state(new_value)

    def run(self) -> None:
        try:
            self.start_mpv()
            self.watcher.start()
        except TimeoutError:
            self.main.post_message(self.Fail())
            return

    def start_mpv(self, timeout: int = 120) -> None:
        self.player.play(self.stream_url)
        self.player.wait_until_playing(timeout=timeout)
        MPVThread.instance = self
        self.main.post_message(self.Started())
        # self.player.observe_property("core-idle", self._watch_core_idle)
        self.player.observe_property("metadata", self._watch_metadata)
        self.player.observe_property("demuxer-cache-state", self._watch_cache)

    def get_options(self) -> dict[str, Any]:
        mpv_options = Config.get_config().player.mpv_options.copy()
        mpv_options["volume"] = Config.get_config().persistant.volume
        if Config.get_config().player.dynamic_range_compression and not mpv_options.get("af"):
            mpv_options["af"] = "acompressor=ratio=4,loudnorm=I=-16:LRA=11:TP=-1.5"
        return mpv_options

    def log_handler(self, loglevel: str, component: str, message: str):
        if component == "display-tags":
            return
            # self._log.debug(component)
        match loglevel:
            case "info":
                level = INFO
            case "warn":
                level = WARNING
            case "debug":
                level = DEBUG
            case _:
                level = DEBUG

        # if "linearizing discontinuity" in message.lower():
        #     self.main.post_message(self.NewSong())
        self._log.log(level=level, msg=f"[{component}] {message}")

    def restart(self, timeout: int = 60) -> None:
        self._log.debug("soft restarting")
        state = self.paused
        self.player.play(self.stream_url)
        self.player.wait_until_playing(timeout=timeout)
        self.paused = state or False

    def hard_restart(self, timeout: int = 60) -> None:
        self._log.debug("hard restarting")
        self.terminate()
        self.player = MPV(**self.get_options())
        self.start_mpv(timeout)

    def play(self) -> None:
        with self._lock:
            self.paused = False
            self.restart()

    def pause(self) -> None:
        with self._lock:
            self.paused = True

    def play_pause(self) -> None:
        with self._lock:
            if self.paused:
                self.play()
            else:
                self.pause()

    def set_volume(self, volume: int) -> None:
        self.volume = volume

    def raise_volume(self, amount: int) -> None:
        self.volume = min(self.volume + amount, 100)

    def lower_volume(self, amount: int) -> None:
        self.volume = max(self.volume - amount, 0)

    def set_ao_volume(self, volume: int) -> None:
        self.ao_volume = volume

    def mute(self) -> None:
        self.muted_volume = self.volume
        self.volume = 0

    def unmute(self) -> None:
        self.volume = self.muted_volume or 1
        self.muted_volume = 0

    def toggle_mute(self) -> None:
        self.mute() if self.muted_volume == 0 else self.unmute()

    def terminate(self) -> None:
        self.player.terminate()
        MPVThread.instance = None

    def terminate_preview(self) -> None:
        pass

    def preview(
        self,
        song_url: str,
    ) -> None:
        if self._pv_lock.locked():
            self.main.post_message(self.PreviewStatus(self.PreviewType.LOCKED))
            return
        Thread(target=self._preview, args=(song_url)).start()

    def _preview(
        self,
        song_url: str,
    ) -> None:
        with self._pv_lock:
            self.main.notify(f"got {song_url}")
            final_url = f"https://cdn.listen.moe/snippets/{song_url}".strip()
            self.pv_player = MPV(ytdl=True, **self.get_options(), log_handler=self.log_handler)
            pv_data = None

            @self.pv_player.event_callback("end-file")
            def check(event: MpvEvent):  # type: ignore
                if isinstance(event.data, MpvEventEndFile) and event.data.reason == MpvEventEndFile.ERROR:
                    self.main.post_message(self.PreviewStatus(self.PreviewType.UNABLE))
                    self.pv_player.wait_for_shutdown()  # type: ignore

            def data(_: dict[str, Any], new_value: dict[str, Any]) -> None:
                pv_data = self.DemuxerCacheState.from_cache_state(new_value)  # type: ignore # noqa: F841

            try:
                self.pv_player.observe_property("demuxer-cache-state", data)
                self.pv_player.play(final_url)
                # self.pv_player.wait_for_property("demuxer-cache-state", cond=bool)
                self.pv_player.wait_until_playing()
                self.pause()
                self.main.post_message(self.PreviewStatus(self.PreviewType.PLAYING, pv_data))
                self.pv_player.wait_for_playback()
                self.play()
                self.main.post_message(self.PreviewStatus(self.PreviewType.FINISHED))
            except ShutdownError:
                self.main.post_message(self.PreviewStatus(self.PreviewType.ERROR))
            finally:
                self.pv_player.terminate()
                if self.paused is not None and self.paused:
                    self.play()
