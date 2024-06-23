from textual.widget import Widget


class BasePage(Widget, can_focus=True):
    def __init__(
        self,
        *children: Widget,
        name: str | None = None,
        id: str | None = None,  # noqa: A002
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(*children, name=name, id=id, classes=classes, disabled=disabled)

    def on_show(self) -> None:
        self.focus()
