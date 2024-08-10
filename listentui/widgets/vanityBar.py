from textual.app import ComposeResult
from textual.containers import Center, Horizontal
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label, Static

from listentui.listen.types import Event, ListenWsData, Requester


class VanityBar(Widget):
    DEFAULT_CSS = """
    VanityBar {
        width: auto;
        height: auto;
        padding-bottom: 1;
        
        #listener {
            height: 1;
        }
        
        #event {
            height: 1;
        }

        #requester {
            height: 1;
            padding-right: 1;
        }
        
        &> Center {
            dock: top;
        }
        
        &> Static {
            width: 1fr;
            height: 1;
        }

        &> Horizontal {
            height: auto;
        }
    }

    """
    listener: reactive[int] = reactive(0, layout=True)
    requester: reactive[Requester | None] = reactive(None, layout=True)
    event: reactive[Event | None] = reactive(None, layout=True)

    def watch_listener(self, value: int) -> None:
        self.query_one("#listener", Label).update(f"{value} Listeners")

    def watch_requester(self, value: Requester | None) -> None:
        if value:
            self.query_one("#requester", Label).update(f"Requested by [red]{value.display_name}[/]")
        else:
            self.query_one("#requester", Label).update("")

    def watch_event(self, value: Event | None) -> None:
        if value:
            self.query_one("#event", Label).update(
                f"[red]♫♪.ılılıll {value.name} llılılı.♫♪[/]"  # noqa: RUF001
            )
        else:
            self.query_one("#event", Label).update("")

    def compose(self) -> ComposeResult:
        yield Center(Label("", id="event"))
        with Horizontal():
            yield Label("", id="listener")
            yield Static()
            yield Label("", id="requester")

    def update_vanity(self, data: ListenWsData) -> None:
        self.listener = data.listener
        self.requester = data.requester
        self.event = data.event
