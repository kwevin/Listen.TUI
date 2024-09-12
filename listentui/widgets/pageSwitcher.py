from __future__ import annotations

from math import ceil
from typing import Self, cast

from textual import events, on
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.css.query import QueryError
from textual.message import Message
from textual.reactive import reactive, var
from textual.validation import Number
from textual.widget import Widget
from textual.widgets import Input, Label


class PageInputSelector(Widget):
    # code borrowed from https://github.com/darrenburns/textual-autocomplete
    DEFAULT_CSS = """
    PageInputSelector {
        layer: page_input_selector;
        display: none;
        width: auto;
        height: 1;
        dock: top;
        background: $surface;
    }

    PageInputSelector Horizontal {
        height: 1;
        width: auto;
    }

    PageInputSelector Input {
        width: auto;
        height: 1;
        padding: 0;
        border: none;
        
        &:focus {
            border: none;
        }

        &>.input--cursor,&>.input--placeholder,&>.input--suggestion,&.-invalid,&.-invalid:focus {
            border: none;
        }

        &.-invalid, &.-invalid:focus {
            color: red;
        }
    }
    """

    def __init__(self, pageswitcher: PageSwitcher, limit: int) -> None:
        super().__init__()
        self.page_switcher = pageswitcher
        self.current = 1
        self.max = limit
        self.input = Input(validators=Number(minimum=1, maximum=limit))

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield self.input
            yield Label(f"/{self.max}", id="lim")

    def on_mount(self) -> None:
        screen_layers = list(self.screen.styles.layers)
        if "page_input_selector" not in screen_layers:
            screen_layers.append("page_input_selector")
        self.screen.styles.layers = tuple(screen_layers)  # type: ignore

    def set_position(self) -> None:
        cursor_pos = self.app.mouse_position
        self.styles.offset = (cursor_pos.x, cursor_pos.y + 1)

    def show(self, current: int, limit: int) -> None:
        self.styles.display = "block"
        self.set_position()
        self.current = current
        self.input.value = f"{current}"
        self.max = limit
        self.query_one("#lim", Label).update(f"/{limit}")
        cast(Number, self.input.validators[0]).maximum = limit
        self.input.focus()

    @on(events.DescendantBlur)
    def hide(self) -> None:
        self.styles.display = "none"

    @on(events.MouseScrollDown)
    def handle_down(self, _) -> None:
        self.current = max(self.current - 1, 0)
        self.input.value = f"{self.current}"

    @on(events.MouseScrollUp)
    def handle_up(self, _) -> None:
        self.current = min(self.current + 1, self.max)
        self.input.value = f"{self.current}"

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.validation_result and event.validation_result.is_valid:
            self.page_switcher.set_page(int(event.value))
            self.page_switcher.focus()


class PageSwitcher(Horizontal, can_focus=True):
    DEFAULT_CSS = """
    PageSwitcher {
        height: 1;
        width: 100%;
        align-horizontal: center;
    }
    PageSwitcher Label {
        width: auto;
        height: 1;

        &.current {
            background: red;
            text-style: bold reverse;
        }
    }

    """
    current_page: var[int] = var(1, init=False, always_update=True)
    _pages_to_render: reactive[list[Label]] = reactive([], recompose=True)

    class PageChanged(Message):
        def __init__(self, page: int) -> None:
            super().__init__()
            self.page = page

    def __init__(self, pages: int | None = None) -> None:
        super().__init__()
        self.end_page = pages or 0
        self.can_render_all = False
        self.reseting = False

    @classmethod
    def calculate(cls, amount_per_page: int, total: int) -> Self:
        return cls(ceil(total / amount_per_page))

    # def render(self) -> RenderResult:
    #     return "".join(self._pages_to_render)

    def compose(self) -> ComposeResult:
        yield from self._pages_to_render

    def on_mount(self) -> None:
        try:
            self.screen.query_one(PageInputSelector)
        except QueryError:
            self.screen.mount(PageInputSelector(self, self.end_page))

    def on_resize(self, event: events.Resize) -> None:
        self._pages_to_render.clear()
        min_size = 12
        if event.size.width < min_size or self.end_page == 0:
            return
        width = event.size.width - 12
        if width - sum(self.size_of_page(page) for page in range(1, self.end_page + 1)) > 0:
            self.can_render_all = True
        else:
            self.can_render_all = False
        self._pages_to_render = self.create_pages()

    def create_pages(self) -> list[Label]:
        if self.end_page == 0:
            return []
        pages_to_render = [
            self.create_prev_page(),
        ]
        if self.can_render_all:
            pages_to_render.extend([self.create_page(page) for page in range(1, self.end_page + 1)])
            pages_to_render.append(self.create_next_page())
            return pages_to_render

        per_side = 3
        # start is visible
        if self.current_page <= 2 + per_side:
            pages_to_render.extend(
                [self.create_page(page) for page in range(1, min(self.end_page - 2, per_side * 2 + 2))]
            )
            pages_to_render.extend([self.create_input_page(), self.create_page(self.end_page), self.create_next_page()])

            return pages_to_render
        # end is visible
        if self.current_page + per_side + 1 >= self.end_page:
            pages_to_render.extend([self.create_page(1), self.create_input_page()])
            pages_to_render.extend(
                [self.create_page(page) for page in range(self.end_page - per_side * 2 - 1, self.end_page + 1)]
            )
            pages_to_render.append(self.create_next_page())
            return pages_to_render

        # both start and end is not visible
        pages_to_render.extend([self.create_page(1), self.create_input_page()])
        pages_to_render.extend(
            [self.create_page(page) for page in range(self.current_page - per_side, self.current_page + per_side + 1)]
        )
        pages_to_render.extend([self.create_input_page(), self.create_page(self.end_page), self.create_next_page()])
        return pages_to_render

    def create_page(self, page: int) -> Label:
        if page == self.current_page:
            label = Label(f"[@click=focused.to_page('{page}')] {page} [/]", id=f"_page-{page}")
            label.add_class("current")
            return label
        return Label(f"[@click=focused.to_page('{page}')] {page} [/]", id=f"_page-{page}")

    def size_of_page(self, page: int) -> int:
        return len(str(page)) + 2

    def create_input_page(self) -> Label:
        return Label("[@click=focused.input('')] … [/]")

    def create_prev_page(self) -> Label:
        return Label("[@click=focused.previous]Prev[/]")

    def create_next_page(self) -> Label:
        return Label("[@click=focused.next]Next[/]")

    def watch_current_page(self, new_page: int) -> None:
        self._pages_to_render = self.create_pages()
        if self.reseting:
            self.reseting = False
            return
        self.post_message(self.PageChanged(new_page))

    def action_previous(self) -> None:
        self.current_page = max(self.current_page - 1, 1)

    def action_next(self) -> None:
        self.current_page = min(self.current_page + 1, self.end_page)

    def action_to_page(self, page: str) -> None:
        self.current_page = int(page)

    def action_input(self) -> None:
        self.screen.query_one(PageInputSelector).show(self.current_page, self.end_page)

    def set_page(self, page: int) -> None:
        self.current_page = page

    def reset(self) -> None:
        self.reseting = True
        self.set_page(1)

    def update(self, new_end_page: int) -> None:
        self.end_page = new_end_page
        self._pages_to_render = self.create_pages()

    def calculate_update_end_page(self, amount_per_page: int, total: int) -> None:
        self.update(ceil(total / amount_per_page))
