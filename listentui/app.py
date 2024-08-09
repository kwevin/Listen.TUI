from textual import work
from textual.app import App

from listentui.data.config import Config
from listentui.screen.login import LoginScreen
from listentui.screen.main import MainScreen
from listentui.utilities.logger import create_logger
from listentui.widgets.player import MPVThread


class ListentuiApp(App[None]):
    TITLE = "LISTEN.moe"

    @work
    async def on_mount(self) -> None:
        create_logger(Config.get_config().advance.stats_for_nerd)
        status = await self.push_screen_wait(LoginScreen())
        if not status:
            self.exit(message="Login failed, please check your username and password")
        self.push_screen(MainScreen())

    def on_unmount(self) -> None:
        Config.get_config().save()
        if MPVThread.instance:
            MPVThread.instance.terminate()

    def action_handle_url(self, url: str) -> None:
        self.app.open_url(url, new_tab=True)


def run() -> None:
    ListentuiApp().run()


if __name__ == "__main__":
    ListentuiApp().run()
