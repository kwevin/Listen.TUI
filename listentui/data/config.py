import sys
from dataclasses import asdict, dataclass, field
from os import environ
from pathlib import Path
from typing import Any

import tomli
import tomli_w
from xdg import xdg_config_home

from listentui import __portable__
from listentui.utilities.constant import PACKAGE_NAME


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
    default_placeholder: str = " ♪"
    """Text to add to achieve minimum length requirement (must be at least 2 characters)"""
    use_fallback: bool = True
    """Whether to use a fallback image when no image is present"""
    fallback: str = "default"
    """Fallback to use when there is no image present ("default" for LISTEN.moe's icon)"""
    use_artist: bool = True
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
    show_small_image: bool = True
    """Whether to show small image (artist image)"""

    def __post_init__(self):
        minimum_length = 2
        if len(self.default_placeholder) < minimum_length:
            raise InvalidConfigError(f"Default Placeholder: must be greater than {minimum_length} characters")


@dataclass
class Display:
    romaji_first: bool = True
    """Prefer romaji first"""
    show_romaji_tooltip: bool = True
    """Show romaji as a tooltip on player hover"""
    user_feed_amount: int = 10
    """Amount of user feed to show"""
    history_amount: int = 100
    """Amount of history to show"""
    open_in_app_browser: bool = True
    """Whether to open clickable content within the app"""
    confirm_before_open: bool = False
    """Show confirmation dialog before opening a clickable content"""


@dataclass
class Player:
    mpv_options: dict[str, Any] = field(default_factory=dict)
    """MPV options to pass to mpv (see https://mpv.io/manual/master/#options)"""
    timeout_restart: int = 20
    """How long to wait before restarting playback"""
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
class Advance:
    show_debug_tool: bool = False
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
    advance: Advance = field(default_factory=Advance)
    persistant: Persistant = field(default_factory=Persistant)


class Config:
    config: "Config | None" = None

    def __init__(self) -> None:
        self.config_root = self._config_root()
        self.config_file = self.config_root.joinpath("config.toml")
        self._conf: dict[str, Any] = {}
        self._client: Client
        self._rich_presence: Presence
        self._display: Display
        self._player: Player
        self._advance: Advance
        self._load_config()
        Config.config = self

    @property
    def config_raw(self) -> dict[str, Any]:
        return self._conf

    @property
    def client(self):
        return self._client

    @property
    def presence(self):
        return self._rich_presence

    @property
    def display(self):
        return self._display

    @property
    def player(self):
        return self._player

    @property
    def advance(self):
        return self._advance

    @property
    def persistant(self):
        return self._persistant

    def _config_root(self) -> Path:
        # TODO: remove this, for testing purposes
        return Path().parent.resolve()
        if __portable__:
            return Path(sys.argv[0]).parent.resolve()

        if sys.platform.startswith(("linux", "darwin", "freebsd", "openbsd")):
            root = xdg_config_home().joinpath(PACKAGE_NAME).resolve()
            if not root.is_dir():
                root.mkdir(parents=True, exist_ok=True)
            return root
        if sys.platform == "win32":
            root = Path(environ["ROAMING"]).joinpath(PACKAGE_NAME).resolve()
            if not root.is_dir():
                root.mkdir(parents=True, exist_ok=True)
            return root
        raise NotImplementedError(f"Not supported: {sys.platform}")

    def _load_config(self) -> None:
        if not self.config_file.is_file():
            self._write_config(self._default())
            self._conf = self._default()
        else:
            with open(self.config_file, "rb") as f:
                self._conf = tomli.load(f)

        self._client = Client(**self._conf["client"])
        self._rich_presence = Presence(**self._conf["presence"])
        self._display = Display(**self._conf["display"])
        self._player = Player(**self._conf["player"])
        self._advance = Advance(**self._conf["advance"])
        self._persistant = Persistant(**self._conf["persistant"])

    def _write_config(self, config: dict[str, Any]) -> None:
        with open(self.config_file, "wb") as f:
            tomli_w.dump(config, f)

    def _default(self) -> dict[str, Any]:
        return asdict(DefaultConfig())

    def save(self):
        self._write_config(
            asdict(
                DefaultConfig(
                    self._client, self._display, self._rich_presence, self._player, self._advance, self._persistant
                )
            )
        )
        self._load_config()

    @classmethod
    def get_config(cls) -> "Config":
        return Config.config or cls()
