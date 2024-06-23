import json
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, Optional

import mpv  # type: ignore
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Horizontal
from textual.message import Message
from textual.reactive import var
from textual.validation import Function, Validator
from textual.widget import Widget
from textual.widgets import Collapsible, Input, Label, Static, Switch, TextArea

from listentui.data.config import Config
from listentui.listen import ListenClient
from listentui.pages.base import BasePage
from listentui.widgets.custom import StaticButton as Button

DOC: dict[str, str] = {
    "client.username": "Your login username",
    "client.password": "Your login password",
    "presence.enable": "Enable discord rich presence",
    "presence.default_placeholder": "Text to add to achieve minimum length requirement (must be at least 2 characters)",
    "presence.use_fallback": "Whether to use a fallback image when no image is present",
    "presence.fallback": "Fallback to use when there is no image present ('default' for LISTEN.moe's icon)",
    "presence.use_artist": "Whether to use artist image as image when no album image is present",
    "presence.detail": "Discord Rich Presence Title",
    "presence.state": "Discord Rich Presence Subtitle",
    "presence.large_text": "Discord Rich Presence Large Image alt-text",
    "presence.small_text": "Discord Rich Presence Small Image alt-text",
    "presence.show_time_left": "Whether to show time remaining",
    "presence.show_small_image": "Whether to show small image (artist image)",
    "display.romaji_first": "Prefer romaji first",
    "display.show_romaji_tooltip": "Show romaji as a tooltip on player hover",
    "display.user_feed_amount": "Amount of user feed to display",
    "display.history_amount": "Amount of history to display",
    "display.open_in_app_browser": "Whether to open clickable content within the app",
    "display.confirm_before_open": "Show confirmation dialog before opening a clickable content",
    "player.timeout_restart": "How long to wait before restarting the player (in seconds)",
    "player.volume_step": "How much to raise/lower volume by",
    "player.dynamic_range_compression": "Enable dynamic range compression, this will add an `af` field into `mpv_options`, will be overwritten if `mpv_options` already has an `af` field set",  # noqa: E501
    "player.mpv_options": "MPV options to pass to mpv (see https://mpv.io/manual/master/#options)",
    "advance.show_debug_tool": "Enable verbose logging and add an additional `log` tab for debugging",
}


@dataclass
class Setting:
    catagory: str
    option: str
    value: Any


class Generic(Horizontal):
    DEFAULT_CSS = """
    Generic {
        height: 3;
        width: 1fr;
    }
    Generic .filler {
        height: 3;
        width: 1fr;
    }
    """

    def __init__(self, setting: Setting, append_id: bool = True) -> None:
        if append_id:
            super().__init__(id=f"setting-{setting.catagory}-{setting.option}")
        else:
            super().__init__()
        self.setting = setting


class GenericSwitch(Generic):
    DEFAULT_CSS = """
    GenericSwitch Label {
        height: 3;
        margin: 1 0 1 1;
        width: auto;
    }
    GenericSwitch Switch {
        margin-right: 1;
    }
    """

    def __init__(self, setting: Setting, append_id: bool = True) -> None:
        super().__init__(setting, append_id)
        self.label = setting.option
        self.default = setting.value

    def compose(self) -> ComposeResult:
        yield Label(str(self.label))
        yield Static(classes="filler")
        yield Switch(value=self.default)

    def on_mount(self) -> None:
        doc = DOC.get(f"{self.setting.catagory}.{self.setting.option}")
        self.query_one(Label).tooltip = doc

    def on_switch_changed(self, event: Switch.Changed) -> None:
        self.setting.value = event.value
        config = Config.get_config()
        setattr(getattr(config, self.setting.catagory), self.setting.option, event.value)
        config.save()


class GenericField(Generic):
    DEFAULT_CSS = """
    GenericField {
        height: 3;
        width: 1fr;
    }
    GenericField Label {
        height: 3;
        margin: 1 0 1 1;
        width: auto;
    }
    GenericField Container {
        height: 3;
        width: 1fr;
        align: left middle;
    }
    GenericField Input {
        height: 3;
        width: 2fr;
        margin-right: 1;
    }
    """

    def __init__(
        self,
        setting: Setting,
        hide_input: bool = False,
        is_int: bool = False,
        validator: Optional[Validator] = None,
        append_id: bool = True,
    ) -> None:
        super().__init__(setting, append_id)
        self.label = setting.option
        self.value = setting.value
        self.hide_input = hide_input
        self.validator = validator
        self.is_int = is_int
        self.input_type: Literal["text", "number"] = "number" if is_int else "text"

    def compose(self) -> ComposeResult:
        yield Container(Label(str(self.label)))
        yield Static(classes="filler")
        yield Input(value=str(self.value), type=self.input_type, password=self.hide_input, validators=self.validator)

    def on_mount(self) -> None:
        doc = DOC.get(f"{self.setting.catagory}.{self.setting.option}")
        self.query_one(Label).tooltip = doc

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.validation_result and not event.validation_result.is_valid:
            return
        self.setting.value = int(event.value) if self.is_int else event.value
        config = Config.get_config()
        setattr(getattr(config, self.setting.catagory), self.setting.option, self.setting.value)
        config.save()


class Login(Generic):
    DEFAULT_CSS = """
    Login {
        height: auto;
        width: 1fr;
        layout: vertical;
    }
    Login > Container {
        height: auto;
        layout: horizontal;
        width: 1fr;
        padding: 1 2 0 0;
        align: right middle;
    }
    Login Button {
        margin-left: 2;
    }
    """

    def __init__(self, setting: Setting) -> None:
        super().__init__(setting)

    def compose(self) -> ComposeResult:
        yield GenericField(self.setting, hide_input=True, append_id=False)
        yield Container(Button("Show", id="show"), Button("Login", variant="primary", id="login"))

    def on_mount(self) -> None:
        client = ListenClient.get_instance()
        if client.logged_in:
            self.query_one("#login", Button).variant = "success"

    @on(Button.Pressed, "#show")
    def toggle_password(self, event: Button.Pressed) -> None:
        input_field = self.query_one("GenericField > Input", Input)
        input_field.password = not input_field.password
        state = input_field.password
        self.query_one("#show", Button).variant = "default" if state else "success"

    @work(group="setting")
    @on(Button.Pressed, "#login")
    async def login(self, event: Button.Pressed) -> None:
        client = ListenClient.get_instance()
        if client.logged_in:
            self.notify("Already logged in", title="Login", timeout=1)
            return

        username: str = self.app.query_one("#setting-client-username", Generic).setting.value
        password: str = self.query_one(GenericField).setting.value
        user = await client.login(username, password)
        if not user:
            self.query_one("#login", Button).variant = "error"
            self.notify("Please check your username and/or password", title="Login Failed", severity="warning")
        else:
            self.query_one("#login", Button).variant = "success"
            self.notify("Successfully logged in", title="Login Success")


class MPVOptions(Generic):
    DEFAULT_CSS = """
    MPVOptions {
        height: auto;
        width: 100%;
        padding-right: 2;
    }
    MPVOptions TextArea {
        height: auto;
    }
    MPVOptions Horizontal {
        width: 1fr;
        height: auto;
        align: right middle;
        padding-top: 1;
    }
    MPVOptions Button {
        margin-left: 2;
    }
    """

    checked: var[bool] = var(False, init=False)

    def __init__(self, setting: Setting) -> None:
        super().__init__(setting)
        self.default_options: dict[str, Any] = setting.value

    def compose(self) -> ComposeResult:
        with Collapsible(title="mpv_options"):
            yield TextArea(
                json.dumps(self.default_options, indent=4),
                language="json",
                theme="monokai",
                show_line_numbers=True,
            )

            with Horizontal():
                yield Button("Check", id="check")
                yield Button("Save", id="save")

    def on_mount(self) -> None:
        doc = DOC.get(f"{self.setting.catagory}.{self.setting.option}")
        self.query_one("CollapsibleTitle").tooltip = doc

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self.query_one("#check", Button).variant = "default"
        self.checked = False

    @work(group="setting-mpv", thread=True)
    def test_mpv(self, options: dict[str, Any]) -> bool:
        try:
            mpv.MPV(**options).terminate()
            return True
        except AttributeError as e:
            # AttributeError("Exception Message", -5, (<mpvHandleObject at>, b'illegal flag', b'no'))
            exception_message: str = e.args[0]
            illegal_flag = bytes(e.args[-1][1]).decode()

            self.notify(
                f"`{illegal_flag}` is an invalid mpv option",
                title=f"{exception_message}",
                severity="warning",
                timeout=5,
            )
        except (ValueError, TypeError) as e:
            # ValueError("Exception Message", -5, (<mpvHandleObject at>, b'illegal value', b'no'))
            exception_message: str = e.args[0]
            flag = bytes(e.args[-1][1]).decode()
            illegal_value = bytes(e.args[-1][2]).decode()

            self.notify(
                f"`{flag}: {illegal_value}` is an invalid value",
                title=f"{exception_message}",
                severity="warning",
                timeout=5,
            )
        except Exception as e:
            self.notify(f"{e}", title="Exception", severity="warning", timeout=5)
        return False

    @on(Button.Pressed, "#check")
    async def check_text_area(self) -> dict[str, Any] | None:
        content = self.query_one(TextArea).text
        if self.checked:
            return json.loads(content)
        try:
            deserialized = json.loads(content)
            self.query_one("#check", Button).variant = "success"
        except json.JSONDecodeError as err:
            self.query_one("#check", Button).variant = "error"
            self.notify(f"{err}", title="JSONDecoderError", severity="warning")
            self.checked = False
            return None

        result = await self.test_mpv(deserialized).wait()
        if not result:
            self.query_one("#check", Button).variant = "error"
            self.checked = False
            return None

        self.checked = True

        return deserialized

    @on(Button.Pressed, "#save")
    async def save_changes(self) -> None:
        if not self.checked:
            result = await self.check_text_area()
            if not result:
                return

        deserialized = json.loads(self.query_one(TextArea).text)
        self.setting.value = deserialized
        config = Config.get_config()
        setattr(getattr(config, self.setting.catagory), self.setting.option, deserialized)
        config.save()


class SettingPage(BasePage):
    DEFAULT_CSS = """
    SettingPage {
        layout: vertical;
        overflow-x: hidden;
        overflow-y: auto;
    }
    SettingPage > Collapsible {
        margin-left: 1;
        margin-right: 1;
    }
    SettingPage Contents > * {
        margin: 1;
    }
    SettingPage #setting-info {
        height: auto;
        align: left middle;
        margin: 1;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [Binding("ctrl+s", "apply", "Apply Changes")]

    class Restart(Message):
        def __init__(self) -> None:
            super().__init__()

    def __init__(self) -> None:
        super().__init__()
        self.config = Config.get_config().config_raw
        self.override: dict[str, Widget] = {
            "client.password": Login(Setting("client", "password", self.config["client"]["password"])),
            "player.mpv_options": MPVOptions(Setting("player", "mpv_options", self.config["player"]["mpv_options"])),
            "presence.default_placeholder": GenericField(
                Setting("presence", "default_placeholder", self.config["presence"]["default_placeholder"]),
                validator=Function(lambda x: len(x) >= 2, failure_description="must be >= 2 characters"),  # noqa: PLR2004
            ),
        }

    def compose(self) -> ComposeResult:
        yield Label("• For more information, hover over the label", id="setting-info")
        for catagory in self.config:
            if catagory == "persistant" and not self.config["advance"]["show_debug_tool"]:
                continue
            with Collapsible(title=catagory.capitalize()):
                for option in self.config[catagory]:
                    field = self.config[catagory][option]
                    setting = Setting(catagory, option, field)

                    override = self.get_override(catagory, option)
                    if override:
                        yield override
                    elif isinstance(field, bool):
                        yield GenericSwitch(setting)
                    elif isinstance(field, str):
                        yield GenericField(setting)
                    elif isinstance(field, int):
                        yield GenericField(setting, is_int=True)

    def get_override(self, catagory: str, option: str) -> Widget | None:
        return self.override.get(f"{catagory}.{option}")

    def action_apply(self) -> None:
        self.notify("Applying changes...")
        self.post_message(self.Restart())


if __name__ == "__main__":
    from textual.app import App
    from textual.widgets import Footer

    class TestApp(App[None]):
        def compose(self) -> ComposeResult:
            yield SettingPage()
            yield Footer()

    app = TestApp()
    app.run()
