from typing import Any, ClassVar

from textual import events, on, work
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Center, Horizontal, Vertical
from textual.reactive import reactive, var
from textual.widget import Widget
from textual.widgets import Button, Label, Static

from ..data import Config, Theme
from ..listen import Event, Requester
from ..listen.client import ListenClient
from .base import BasePage
from .custom import ToggleButton
from .mpvplayer import MPVStreamPlayer
from .websocket import ListenWebsocket, SongContainer


class VanityBar(Widget):
    DEFAULT_CSS = """
    VanityBar {
        width: auto;
        height: auto;
    }
    VanityBar #listener {
        width: auto;
        height: 1;
    }
    VanityBar #requester {
        width: auto;
        height: 1;
        padding-right: 1;
    }
    VanityBar #event {
        width: auto;
        height: 1;
    }
    VanityBar Center {
        height: auto;
        dock: top;
    }
    VanityBar Horizontal {
        height: auto;
    }
    VanityBar Static {
        width: 1fr;
        height: 1;
    }
    """
    listener: reactive[int] = reactive(0, layout=True)
    requester: reactive[Requester | None] = reactive(None, layout=True)
    event: reactive[Event | None] = reactive(None, layout=True)

    def watch_listener(self, value: int) -> None:
        self.query_one("#listener", Label).update(f"{value} Listeners")

    def watch_requester(self, value: Requester | None) -> None:
        if value:
            self.query_one("#requester", Label).update(f"Requested by [{Theme.ACCENT}]{value.display_name}[/]")
        else:
            self.query_one("#requester", Label).update("")

    def watch_event(self, value: Event | None) -> None:
        if value:
            self.query_one("#event", Label).update(
                f"[{Theme.ACCENT}]♫♪.ılılıll {value.name} llılılı.♫♪[/]"  # noqa: RUF001
            )
        else:
            self.query_one("#event", Label).update("")

    def compose(self) -> ComposeResult:
        yield Center(Label("", id="event"))
        with Horizontal():
            yield Label("", id="listener")
            yield Static()
            yield Label("", id="requester")


class PlayButton(ToggleButton):
    DEFAULT_CSS = f"""
    PlayButton.-toggled {{
        background: {Theme.BUTTON_BACKGROUND};
        text-style: none;
    }}
    PlayButton.-disabled {{
        tint: black 80%;
    }}
    """
    is_playing: reactive[bool] = reactive(True, init=False, layout=True, always_update=True)

    def __init__(self):
        super().__init__("Pause", "Play")

    def watch_is_playing(self, new: bool) -> None:
        self.app.query_one(MPVStreamPlayer).is_playing = new
        if new:
            self.disable()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.is_playing = not self.is_playing

    def enable(self) -> None:
        self.remove_class("-disabled")
        self.disabled = False

    def disable(self) -> None:
        self.add_class("-disabled")
        self.disabled = True


class FavoriteButton(ToggleButton):
    def __init__(self):
        super().__init__("Favorite", check_user=True, id="favoritebutton")


class VolumeButton(ToggleButton):
    volume: var[int] = var(Config.get_config().persistant.volume, init=False)
    muted: var[bool] = var(False, init=False)

    def __init__(self):
        super().__init__(f"Volume: {Config.get_config().persistant.volume}", "Muted")

    def watch_volume(self, new: int) -> None:
        if new == 0:
            self.muted = True
            self.set_toggle_state(True)
            return
        self.label = f"Volume: {new}"
        self.update_default_label(self.label)
        self.app.query_one(MPVStreamPlayer).volume = new
        Config.get_config().persistant.volume = new

    def watch_muted(self, new: bool) -> None:
        self.app.query_one(MPVStreamPlayer).volume = 0 if new else self.volume

    def validate_volume(self, volume: int) -> int:
        min_volume = 0
        max_volume = 100
        if volume < min_volume:
            volume = 0
        if volume > max_volume:
            volume = 100
        return volume

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.muted = not self.muted

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        if self.muted:
            return
        self.volume -= 1

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        if self.muted:
            return
        self.volume += 1


class PlayerPage(BasePage):
    DEFAULT_CSS = f"""
    PlayerPage {{
        align: center middle;
        layers: below above;
        background: {Theme.BACKGROUND}
    }}
    PlayerPage MPVStreamPlayer {{
        layer: above;
        width: 100%;
        height: 100%;
    }}
    PlayerPage Vertical {{
        height: auto;
        margin: 0 12 0 12;
    }}
    PlayerPage #buttons {{
        align: left middle;
        height: auto;
        width: 100%;
    }}
    PlayerPage Button {{
        margin: 1 2 0 0;
    }}
    PlayerPage #filler {{
        width: 1fr;
    }}
    PlayerPage VolumeButton {{
        margin: 1 0 0 0;
    }}
    PlayerPage VanityBar {{
        margin: 0 1 1 1;
    }}
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("space", "play_pause", "Play/Pause"),
        Binding("f", "favorite", "Favorite"),
        Binding("up,k", "volume_up", "Volume Up"),
        Binding("down,j", "volume_down", "Volume Down"),
        Binding("m", "mute", "Mute"),
        Binding("r", "restart", "Restart Player"),
    ]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

    def compose(self) -> ComposeResult:
        yield MPVStreamPlayer()
        with Vertical():
            yield VanityBar()
            yield ListenWebsocket()
            with Horizontal(id="buttons"):
                yield PlayButton()
                yield FavoriteButton()
                yield Static(id="filler")
                yield VolumeButton()

    # def on_mount(self) -> None:
    #    border-top: round {Theme.ACCENT};
    #    border-title-align: center;
    # self.query_one(Vertical).border_title = " Requested by Test Subject "

    def action_play_pause(self) -> None:
        play_button = self.query_one(PlayButton)
        play_button.is_playing = not play_button.is_playing

    def action_favorite(self) -> None:
        favorite_button = self.query_one(FavoriteButton)
        favorite_button.toggle_state()
        self.favorite()

    def action_volume_up(self) -> None:
        volume_button = self.query_one(VolumeButton)
        volume_button.volume += Config.get_config().player.volume_step

    def action_volume_down(self) -> None:
        volume_button = self.query_one(VolumeButton)
        volume_button.volume -= Config.get_config().player.volume_step

    def action_mute(self) -> None:
        volume_button = self.query_one(VolumeButton)
        volume_button.toggle_state()

    def action_restart(self) -> None:
        self.query_one(PlayButton).is_playing = True
        self.query_one(MPVStreamPlayer).hard_restart()

    @on(FavoriteButton.Pressed, "#favoritebutton")
    @work(group="player_button")
    async def favorite(self) -> None:
        client = ListenClient.get_instance()
        data = self.query_one(ListenWebsocket).data
        if data:
            await client.favorite_song(data.song.id)

    @on(MPVStreamPlayer.Restarted)
    def on_player_restart(self, event: MPVStreamPlayer.Restarted) -> None:
        self.query_one(PlayButton).enable()
        if self.query_one(VolumeButton).muted:
            self.query_one(MPVStreamPlayer).volume = 0

    @on(ListenWebsocket.Updated)
    async def on_listen_websocket_updated(self, event: ListenWebsocket.Updated) -> None:
        vanity_bar = self.query_one(VanityBar)
        vanity_bar.listener = event.data.listener
        vanity_bar.requester = event.data.requester
        vanity_bar.event = event.data.event

        client = ListenClient.get_instance()
        if client.logged_in:
            favorited: bool = await client.check_favorite(event.data.song.id)
            self.query_one(FavoriteButton).set_toggle_state(favorited)

        show_tooltip = Config.get_config().display.show_romaji_tooltip
        if show_tooltip:
            song = await client.song(event.data.song.id)
            if song:
                if song.title_romaji:
                    self.query_one("ListenWebsocket > SongContainer", SongContainer).set_tooltips(song.title_romaji)
                else:
                    self.query_one("ListenWebsocket > SongContainer", SongContainer).set_tooltips(None)
