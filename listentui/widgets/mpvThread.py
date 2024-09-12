# pyright: reportUnknownMemberType=false, reportMissingTypeStubs=false
from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from logging import DEBUG, INFO, WARNING, getLogger
from threading import Lock, Thread
from time import sleep
from typing import Any, Callable, Self, Type

from mpv import MPV, MpvEvent, MpvEventEndFile, ShutdownError
from rich.repr import Result, RichReprResult
from textual.message import Message
from textual.widget import Widget

from listentui.data.config import Config


class PreviewType(Enum):
    UNABLE = 1
    ERROR = 2
    LOCKED = 3
    PLAYING = 4
    FINISHED = 5
    DATA = 6
    DONE = 7


class PreviewStatus:
    def __init__(self, state: PreviewType, other: Any = None) -> None:
        self.state = state
        self.other = other

    def __rich_repr__(self) -> Result:
        yield self.state
        yield self.other


class MPVWatcher(Thread):
    def __init__(self, thread: MPVThread) -> None:
        super().__init__(name="MPVWatcher", daemon=True)
        self._log = getLogger(__name__)
        self.is_terminated = False
        self.player = thread
        self.base_timeout = Config.get_config().player.restart_timeout
        self.retries = 0
        self.soft_retry_cap = 5
        self.hard_retry_cap = 10
        self.timeout_cap = 60
        self.terminated = False

    def run(self) -> None:
        while not self.terminated:
            if not self.is_player_alive():
                sleep(1)
                self._log.debug("Player is not alive, sleeping...")
                continue
            if self.player.is_restarting():
                self._log.debug("Player is currently restarting...")
                sleep(1)
                continue
            if self.is_not_playing():
                sleep(Config.get_config().player.inactivity_timeout)
                if self.is_not_playing():
                    self.dispatch_restart()
                continue
            sleep(1)

    def is_player_alive(self) -> bool:
        return not self.player.player.core_shutdown

    def is_not_playing(self) -> bool:
        return bool(self.player.core_idle is True and self.player.paused is False)

    def dispatch_restart(self) -> None:
        self.retries += 1
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
            self.player.main.post_message(
                self.player.FailedRestart(self.retries, timeout, self.soft_retry_cap, self.hard_retry_cap)
            )

    def terminate(self) -> None:
        self.terminated = True


class MPVThread(Thread):
    instance: MPVThread | None = None
    pv_thread: MPVPreviewer | None = None

    def __init__(self, main: Widget) -> None:
        super().__init__(name="MPVThread", daemon=True)
        self.main = main
        self.stream_url = "https://listen.moe/stream"
        self.player = MPV(ytdl=True, **self.get_options(), terminal=False, log_handler=self.log_handler)
        self.watcher = MPVWatcher(self)
        self.muted_volume = 0
        self.cache: MPVThread.DemuxerCacheState | None = None
        self._metadata: MPVThread.Metadata | None = None
        self._log = getLogger(__name__)
        self._restart_lock = Lock()
        self.terminated = False

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

        def __rich_repr__(self) -> Result:
            yield self.cache_end
            yield self.cache_duration
            yield self.fw_byte
            yield self.total_bytes
            yield self.seekable_start
            yield self.seekable_end

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

    # This is definitely not future proof
    class NewSong(Message):
        def __init__(self) -> None:
            super().__init__()

    class UnderRun(Message):
        def __init__(self) -> None:
            super().__init__()

    @property
    def paused(self) -> bool | None:
        return bool(self._get_value("pause"))

    @paused.setter
    def paused(self, state: bool):
        with contextlib.suppress(ShutdownError):
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
        with contextlib.suppress(ShutdownError):
            self.player.volume = volume

    @property
    def ao_volume(self) -> float:
        ao_volume = self._get_value("ao_volume")
        if not ao_volume:
            return 0
        return float(ao_volume)

    @ao_volume.setter
    def ao_volume(self, volume: int):
        with contextlib.suppress(ShutdownError):
            self.player.ao_volume = volume

    def _get_value(self, value: str, *args: Any) -> Any | None:
        try:
            return getattr(self.player, value, *args)
        except (RuntimeError, ShutdownError, OSError):
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

        while not self.terminated:
            sleep(1)
        MPVThread.instance = None
        return

    def setup_mpv(self, timeout: int = 120) -> None:
        self.player.play(self.stream_url)
        self.player.wait_until_playing(timeout=timeout)
        # self.player.observe_property("core-idle", self._watch_core_idle)
        self.player.observe_property("metadata", self._watch_metadata)
        self.player.observe_property("demuxer-cache-state", self._watch_cache)

    def start_mpv(self, timeout: int = 120) -> None:
        self.setup_mpv(timeout)
        MPVThread.instance = self
        self.main.post_message(self.Started())

    @staticmethod
    def get_options() -> dict[str, Any]:
        mpv_options = Config.get_config().player.mpv_options.copy()
        mpv_options["volume"] = Config.get_config().persistant.volume
        if Config.get_config().player.dynamic_range_compression and not mpv_options.get("af"):
            mpv_options["af"] = "acompressor=ratio=4,loudnorm=I=-16:LRA=11:TP=-1.5"
        return mpv_options

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

        if "linearizing discontinuity" in message.lower():
            self.main.post_message(MPVThread.NewSong())
        if "audio device underrun" in message.lower():
            self.main.post_message(MPVThread.UnderRun())
        self._log.log(level=level, msg=f"[{component}] {message}")

    def restart(self, timeout: int = 60) -> None:
        with self._restart_lock:
            self._log.debug("soft restarting")
            try:
                state = self.paused
                self.player.play(self.stream_url)
                self.player.wait_until_playing(timeout=timeout)
                self.paused = state or False
            except ShutdownError:
                self._log.debug("Libmpv unexpectedly shutdown during the restart")
                self.hard_restart()
            else:
                self.main.post_message(self.SuccessfulRestart())

    def safe_restart(self) -> None:
        with contextlib.suppress(TimeoutError):
            self.restart()

    def safe_hard_restart(self) -> None:
        with contextlib.suppress(TimeoutError):
            self.hard_restart()

    def hard_restart(self, timeout: int = 60) -> None:
        with self._restart_lock:
            self._log.debug("hard restarting")
            self.terminate()
            self.player = MPV(**self.get_options())
            self.start_mpv(timeout)

    def is_restarting(self) -> bool:
        return self._restart_lock.locked()

    def play(self) -> None:
        self.paused = False
        self.restart()

    def pause(self) -> None:
        self.paused = True

    def play_pause(self) -> None:
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
        self.watcher.terminate()
        self.terminated = True

    @staticmethod
    def terminate_preview() -> None:
        if MPVThread.pv_thread and MPVThread.pv_thread.is_alive():
            MPVThread.pv_thread.terminate()
            MPVThread.pv_thread.join(timeout=20)

    @staticmethod
    def preview(song_url: str, callback: Callable[[PreviewStatus], Any]) -> None:
        final_url = f"https://cdn.listen.moe/snippets/{song_url}".strip()
        if MPVThread.pv_thread and MPVThread.pv_thread.is_alive():
            callback(PreviewStatus(PreviewType.LOCKED))
            return
        MPVThread.pv_thread = MPVPreviewer(final_url, callback, MPVThread.instance)
        MPVThread.pv_thread.start()


class MPVPreviewer(Thread):
    def __init__(
        self, final_url: str, callback: Callable[[PreviewStatus], Any], main_player: MPVThread | None = None
    ) -> None:
        super().__init__(name="MPVPreviewer", daemon=True)
        self.final_url = final_url
        self.callback = callback
        self.main_player = main_player
        self.terminated = False
        self.player: MPV | None = None

    def run(self) -> None:
        options = MPVThread.get_options()
        if self.main_player and self.main_player.volume and self.main_player.volume != 0:
            options["volume"] = self.main_player.volume
        options.update({"cache": True, "cache_pause_initial": True, "cache_pause_wait": 15})
        player = MPV(ytdl=True, terminal=False, **options)
        self.player = player

        def safe_call(*args: PreviewStatus):
            if self.terminated:
                return
            Thread(target=self.callback, args=args, daemon=True).start()

        def safe_play():
            try:
                if self.main_player:
                    self.main_player.play()
            except Exception:
                pass

        @player.event_callback("end-file")
        def check(event: MpvEvent):  # type: ignore
            if isinstance(event.data, MpvEventEndFile) and event.data.reason == MpvEventEndFile.ERROR:
                safe_call(PreviewStatus(PreviewType.UNABLE))
                self.terminated = True

        @player.property_observer("demuxer-cache-state")
        def data(property_name: Any, new_value: dict[str, Any] | None) -> None:  # type: ignore
            if new_value is None:
                return
            pv_data = MPVThread.DemuxerCacheState.from_cache_state(new_value)
            safe_call(PreviewStatus(PreviewType.DATA, pv_data))

        try:
            player.play(self.final_url)
            player.wait_until_playing(timeout=20)
            safe_call(PreviewStatus(PreviewType.PLAYING))
            if self.main_player:
                self.main_player.pause()
            player.wait_for_playback(timeout=20)
            safe_call(PreviewStatus(PreviewType.FINISHED))
        except Exception:
            safe_call(PreviewStatus(PreviewType.ERROR))
        else:
            safe_call(PreviewStatus(PreviewType.DONE))

        player.terminate()
        if self.main_player and self.main_player.paused is not None and self.main_player.paused:
            Thread(name="restarting mpv", target=safe_play, daemon=True).start()

    def terminate(self) -> None:
        self.terminated = True
        if self.player:
            self.player.terminate()
