import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import tomli
import tomli_w


class InvalidConfigError(Exception):
    pass


@dataclass
class Client:
    username: str = ""
    """LISTEN.moe login username"""
    password: str = ""
    """LISTEN.moe login password"""


@dataclass
class Presence:
    enable: bool = True
    """Enable discord's rich presence"""
    type: int = 2
    """Type of presence (0 or 2)"""
    default_placeholder: str = " ♪"
    """Text to add to achieve minimum length requirement (must be at least 2 characters)"""
    use_fallback: bool = True
    """Whether to use a fallback image when no image is present"""
    fallback: str = "default"
    """Fallback to use when there is no image present ("default" for LISTEN.moe's icon)"""
    use_artist: bool = False
    """Whether to use artist image as image when no album image is present"""
    detail: str = "${title}"
    """Discord Rich Presence Title"""
    state: str = "${artist}"
    """Discord Rich Presence Subtitle"""
    large_text: str = "${source} ${title}"
    """Discord Rich Presence Large Image alt-text"""
    small_text: str = "${artist}"
    """Discord Rich Presence Small Image alt-text"""
    show_time_left: bool = True
    """Whether to show time remaining"""
    show_artist_as_small_icon: bool = False
    """Whether to show artist as small image icon"""

    def __post_init__(self):
        minimum_length = 2
        if len(self.default_placeholder) < minimum_length:
            raise InvalidConfigError(f"Default Placeholder: must be greater than {minimum_length} characters")


@dataclass
class Display:
    romaji_first: bool = True
    """Prefer romaji first"""


@dataclass
class Player:
    mpv_options: dict[str, Any] = field(default_factory=dict)
    """MPV options to pass to mpv (see https://mpv.io/manual/master/#options)"""
    inactivity_timeout: int = 5
    """How long to wait after the player becomes inactive before restarting"""
    restart_timeout: int = 20
    """How long to wait for playback after restarting"""
    volume_step: int = 5
    """How much to raise/lower volume by"""
    dynamic_range_compression: bool = True
    """Enable dynamic range compression, will be over-ridden if specified in `mpv_options`"""

    def __post_init__(self):
        if not self.mpv_options:
            self.mpv_options = {
                "ad": "vorbis",
                "cache": True,
                "cache_secs": 20,
                "cache_pause_initial": True,
                "cache_pause_wait": 3,
                "demuxer_lavf_linearize_timestamps": True,
            }


@dataclass
class Downloader:
    use_radio_metadata: bool = True
    """Use the radio given metadata over source"""


@dataclass
class Advance:
    stats_for_nerd: bool = False
    """Enable verbose logging and more"""


@dataclass
class Persistant:
    volume: int = 100
    token: str = ""


@dataclass
class DefaultConfig:
    client: Client = field(default_factory=Client)
    display: Display = field(default_factory=Display)
    presence: Presence = field(default_factory=Presence)
    player: Player = field(default_factory=Player)
    downloader: Downloader = field(default_factory=Downloader)
    advance: Advance = field(default_factory=Advance)
    persistant: Persistant = field(default_factory=Persistant)


class Config:
    config: "Config | None" = None

    def __init__(self) -> None:
        self.config_root = self.get_config_root()
        self.config_file = self.config_root.joinpath("config.toml")
        self._conf: dict[str, Any] = {}
        self.client: Client
        self.presence: Presence
        self.display: Display
        self.player: Player
        self.downloader: Downloader
        self.advance: Advance
        self.persistant: Persistant
        self._load_config()
        Config.config = self

    @property
    def config_raw(self) -> dict[str, Any]:
        return self._conf

    def get_config_root(self) -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.argv[0]).parent.resolve()
        return Path(__package__ or os.getcwd()).parent.resolve()
        # if __portable__:
        #     return Path(sys.argv[0]).parent.resolve()

        # if sys.platform.startswith(("linux", "darwin", "freebsd", "openbsd")):
        #     root = xdg_config_home().joinpath(PACKAGE_NAME).resolve()
        #     if not root.is_dir():
        #         root.mkdir(parents=True, exist_ok=True)
        #     return root
        # if sys.platform == "win32":
        #     root = Path(environ["ROAMING"]).joinpath(PACKAGE_NAME).resolve()
        #     if not root.is_dir():
        #         root.mkdir(parents=True, exist_ok=True)
        #     return root
        # raise NotImplementedError(f"Not supported: {sys.platform}")

    def _load_config(self) -> None:
        if not self.config_file.is_file():
            self._write_config(self._default())
            self._conf = self._default()
        else:
            with open(self.config_file, "rb") as f:
                self._conf = tomli.load(f)

        self.client = Client(**self._conf["client"])
        self.presence = Presence(**self._conf["presence"])
        self.display = Display(**self._conf["display"])
        self.player = Player(**self._conf["player"])
        self.downloader = Downloader(**self._conf["downloader"])
        self.advance = Advance(**self._conf["advance"])
        self.persistant = Persistant(**self._conf["persistant"])

    def _write_config(self, config: dict[str, Any]) -> None:
        with open(self.config_file, "wb") as f:
            tomli_w.dump(config, f)

    def _default(self) -> dict[str, Any]:
        return asdict(DefaultConfig())

    def save(self):
        self._write_config(
            asdict(
                DefaultConfig(
                    self.client,
                    self.display,
                    self.presence,
                    self.player,
                    self.downloader,
                    self.advance,
                    self.persistant,
                )
            )
        )
        self._load_config()

    @classmethod
    def get_config(cls) -> "Config":
        return Config.config or cls()
