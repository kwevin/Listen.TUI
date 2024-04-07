from textual import on, work
from textual.app import App

from ..data import Config
from ..listen import ListenClient
from ..screen import Main
from ..utilities import create_logger
from ..widgets import SettingPage


class ListentuiApp(App[None]):
    TITLE = "LISTEN.moe"

    async def on_mount(self) -> None:
        create_logger(Config.get_config().advance.show_debug_tool)
        await self.login().wait()
        self.push_screen(Main())

    @work
    async def login(self) -> None:
        config = Config.get_config()
        username = config.client.username
        password = config.client.password
        token = config.persistant.token
        if username and password:
            client = await ListenClient.login(username, password, token)
            if not client:
                print("Login failed, please check your username and password")
                return
        else:
            client = ListenClient.get_instance()

        user = client.current_user
        if user and user.token:
            config = Config.get_config()
            config.persistant.token = user.token
            config.save()

    @on(SettingPage.Restart)
    async def restart(self) -> None:
        await self.login().wait()
        await self.recompose()
        self.push_screen(Main())


def run() -> None:
    ListentuiApp().run()


if __name__ == "__main__":
    ListentuiApp().run()
