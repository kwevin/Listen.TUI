from typing import ClassVar

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.reactive import var
from textual.widgets import Static

from listentui.data.config import Config
from listentui.listen.client import ListenClient
from listentui.listen.interface import ListenWsData
from listentui.pages.base import BasePage
from listentui.widgets.buttons import ToggleButton
from listentui.widgets.mpvThread import MPVThread
from listentui.widgets.player import Player


class VolumeButton(ToggleButton):
    volume: var[int] = var(Config.get_config().persistant.volume, init=False)
    muted: var[bool] = var(False)

    def __init__(self, id: str | None = None):  # noqa: A002
        super().__init__(f"{Config.get_config().persistant.volume}", "Muted", id=id)

    def watch_volume(self, new: int) -> None:
        self.label = f"{new}"
        self.update_default_label(self.label)
        self.app.query_one(Player).player.set_volume(new)
        Config.get_config().persistant.volume = new

    def watch_muted(self, new: bool) -> None:
        self.set_toggle_state(new)
        self.app.query_one(Player).player.set_volume(0) if new else self.app.query_one(Player).player.set_volume(
            self.volume
        )
        self.refresh_bindings()

    def validate_volume(self, volume: int) -> int:
        min_volume = 0
        max_volume = 100
        if volume < min_volume:
            volume = 0
        if volume > max_volume:
            volume = 100
        return volume

    def on_button_pressed(self) -> None:
        self.toggle()
        self.set_toggle_state(self.muted)

    def on_mouse_scroll_down(self) -> None:
        if self.muted:
            return
        self.volume -= 1

    def on_mouse_scroll_up(self) -> None:
        if self.muted:
            return
        self.volume += 1

    def toggle(self) -> None:
        self.muted = not self.muted


class HomePage(BasePage):
    DEFAULT_CSS = """
    HomePage {
        align: center middle;
    }
    HomePage > Vertical {
        height: auto;
        margin: 0 12 0 12;

        & Label {
            width: auto;
            height: auto;
        }
        
        &> Horizontal {
            align: left middle;
            height: auto;
            width: 1fr;

            & ToggleButton {
                margin: 0 2 0 0;
            }

            & #vol {
                margin: 0 0 0 0;
            }
        }
    }

    MPVPlayer {
        height: 1;
        padding: 0 1;
        margin-bottom: 1;
    }

    #filler { 
        width: 1fr;
    }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("space", "play_pause", "Play/Pause"),
        Binding("f", "favorite", "Favorite"),
        Binding("up,k", "volume_up", "Volume Up"),
        Binding("down,j", "volume_down", "Volume Down"),
        Binding("m", "mute", "Toggle Mute"),
        Binding("r", "soft_restart", "Restart Player"),
        Binding("ctrl+r", "hard_restart", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.started = False
        self.favorited = False
        self.player = Player()

    def compose(self) -> ComposeResult:
        with Vertical():
            yield self.player
            with Horizontal(id="buttons"):
                yield ToggleButton("Play", "Pause", id="playpause")
                yield ToggleButton("Favorite", "Favorited", True, True, id="favorite")
                yield Static(id="filler")
                yield VolumeButton(id="vol")

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if self.started is False:
            return None
        if action == "play_pause":
            return True if not self.query_one("#playpause", ToggleButton).disabled else None
        if action == "favorite":
            return ListenClient.get_instance().logged_in
        if action in {"volume_up", "volume_down"}:
            return None if self.query_one("#vol", VolumeButton).muted else True
        if action == "soft_restart":
            return None if self.player.player.is_restarting() else True
        return True

    def on_mount(self) -> None:
        self.query_one("#playpause", ToggleButton).disabled = True
        self.query_one("#vol", VolumeButton).disabled = True

        self.query_one(Player).websocket_update.subscribe(self, self.get_song_favorited_status, immediate=True)  # type: ignore

    @on(ToggleButton.Pressed, "#playpause")
    def action_play_pause(self) -> None:
        if self.player.player.paused is None:
            return
        if self.player.player.paused is True:
            self.query_one("#playpause", ToggleButton).disabled = True
        self.run_worker(self.player.player.play_pause, thread=True)
        self.query_one("#playpause", ToggleButton).set_toggle_state(not self.player.player.paused)
        self.refresh_bindings()

    @work
    async def get_song_favorited_status(self, _: ListenWsData) -> None:
        if self.player.ws_data is None:
            return
        client = ListenClient.get_instance()
        if client.logged_in:
            self.favorited = await client.check_favorite(self.player.ws_data.song.id)
            self.query_one("#favorite", ToggleButton).set_toggle_state(self.favorited)

    @on(ToggleButton.Pressed, "#favorite")
    @work
    async def action_favorite(self) -> None:
        self.favorited = not self.favorited
        self.query_one("#favorite", ToggleButton).set_toggle_state(self.favorited)
        if self.player.ws_data is None:
            return
        client = ListenClient.get_instance()
        await client.favorite_song(self.player.ws_data.song.id)

    @on(MPVThread.Started)
    def enable_functionality(self) -> None:
        self.started = True
        self.query_one("#playpause", ToggleButton).disabled = False
        self.query_one("#vol", VolumeButton).disabled = False
        self.refresh_bindings()

    @on(MPVThread.SuccessfulRestart)
    def enable_button(self) -> None:
        self.query_one("#playpause", ToggleButton).disabled = False
        self.refresh_bindings()

    def action_volume_up(self) -> None:
        self.player.player.raise_volume(self.config.player.volume_step)
        self.query_one(VolumeButton).volume = self.player.player.volume

    def action_volume_down(self) -> None:
        self.player.player.lower_volume(self.config.player.volume_step)
        self.query_one(VolumeButton).volume = self.player.player.volume

    def action_mute(self) -> None:
        self.player.player.toggle_mute()
        self.query_one(VolumeButton).toggle()

    def action_soft_restart(self) -> None:
        if not self.player.player.is_restarting():
            self.run_worker(self.player.player.safe_restart, thread=True)
        self.refresh_bindings()

    def action_hard_restart(self) -> None:
        if not self.player.player.is_restarting():
            self.run_worker(self.player.player.safe_hard_restart, thread=True)
        self.refresh_bindings()
