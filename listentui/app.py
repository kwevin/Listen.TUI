from contextlib import suppress

from textual import on, work
from textual.app import App

from listentui.data.config import Config
from listentui.listen.client import ListenClient
from listentui.listen.interface import Base
from listentui.pages.setting import SettingPage
from listentui.screen.login import LoginScreen
from listentui.screen.main import MainScreen
from listentui.utilities.logger import create_logger
from listentui.widgets.player import MPVThread


class ListentuiApp(App[str]):
    TITLE = "LISTEN.moe"

    @work
    async def on_mount(self) -> None:
        create_logger(Config.get_config().advance.stats_for_nerd)
        status = await self.push_screen_wait(LoginScreen())
        if not status:
            self.exit(return_code=1, message="Login failed, please check your username and password")
            return
        # configure the client
        Base.romaji_first = Config.get_config().display.romaji_first

        self.push_screen(MainScreen())

    async def on_unmount(self) -> None:
        Config.get_config().save()
        if MPVThread.instance:
            MPVThread.instance.terminate()
        with suppress(AttributeError):
            await ListenClient.get_instance().close()

    def action_handle_url(self, url: str) -> None:
        self.app.open_url(url, new_tab=True)

    @on(SettingPage.SettingApplied)
    async def apply_setting(self) -> None:
        await self.recompose()
        await self.on_unmount()
        self.on_mount()


def run() -> None:
    output = ListentuiApp().run()
    if output is not None:
        print(output)


if __name__ == "__main__":
    run()
