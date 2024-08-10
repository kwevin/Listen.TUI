from gql.transport.exceptions import TransportQueryError
from textual import work
from textual.app import ComposeResult
from textual.containers import Center
from textual.screen import Screen
from textual.widgets import Label, Static

from listentui.data.config import Config
from listentui.listen.client import ListenClient


class LoginScreen(Screen[bool]):
    DEFAULT_CSS = """
    LoginScreen {
        width: 1fr;
        height: 1fr;
        align: center middle;
    }
    Static {
        width: auto;
        height: auto;
        margin-bottom: 1;
    }
    Label {
        width: auto;
        min-width: 11;
        height: auto;
        
        &.success {
            color: green;
        }

        &.error {
            color: red;
        }
    }
    """
    SPLASH = r"""
██╗     ██╗███████╗████████╗███████╗███╗   ██╗████████╗██╗   ██╗██╗
██║     ██║██╔════╝╚══██╔══╝██╔════╝████╗  ██║╚══██╔══╝██║   ██║██║
██║     ██║███████╗   ██║   █████╗  ██╔██╗ ██║   ██║   ██║   ██║██║
██║     ██║╚════██║   ██║   ██╔══╝  ██║╚██╗██║   ██║   ██║   ██║██║
███████╗██║███████║   ██║   ███████╗██║ ╚████║██╗██║   ╚██████╔╝██║
╚══════╝╚═╝╚══════╝   ╚═╝   ╚══════╝╚═╝  ╚═══╝╚═╝╚═╝    ╚═════╝ ╚═╝
"""

    def __init__(self) -> None:
        super().__init__()
        self.state = True

    def compose(self) -> ComposeResult:
        yield Center(Static(self.SPLASH))
        yield Center(Label(id="status"))

    def on_mount(self) -> None:
        self.query_one("#status").loading = True
        self.login()

    def set_success(self) -> None:
        status = self.query_one("#status", Label)
        status.loading = False
        status.add_class("success")
        status.update("Success!")
        self.dismiss(True)
        # self.set_timer(0.5, lambda: self.dismiss(True))

    def set_error(self, message: str | None = None) -> None:
        self.state = False
        status = self.query_one("#status", Label)
        status.loading = False
        status.add_class("error")
        status.update("Login failed, please check your username and password" if message is None else message)

    async def on_click(self) -> None:
        if not self.state:
            self.dismiss(False)

    @work
    async def login(self) -> None:
        config = Config.get_config()
        username = config.client.username
        password = config.client.password
        token = config.persistant.token
        if username and password:
            client = await ListenClient.login(username, password, token)
            if isinstance(client, TransportQueryError):
                self.set_error(str(client.errors[0].get("message")) if client.errors else None)
                return
        else:
            client = ListenClient.get_instance()

        user = client.current_user
        if user and user.token:
            config.persistant.token = user.token
            config.save()
        else:
            config.persistant.token = ""
            config.save()

        self.set_success()
