from typing import Any, ClassVar, Literal

from rich.console import RenderableType
from rich.repr import Result
from rich.text import Span, Text
from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Horizontal
from textual.message import Message
from textual.reactive import reactive, var
from textual.widget import Widget
from textual.widgets import Button, DataTable, Label, ListItem, ListView, ProgressBar, Static

from ..data import Config, Theme
from ..listen import ListenClient
from ..listen.types import Song


class TextRange:
    def __init__(self, start: int, end: int) -> None:
        self.start = start
        self.end = end

    def __hash__(self) -> int:
        return hash((self.start, self.end))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TextRange):
            return NotImplemented
        return (self.start, self.end) == (other.start, other.end)

    def within_range(self, value: int) -> bool:
        return value >= self.start and value < self.end


class ScrollableLabel(Widget):
    DEFAULT_CSS = """
    ScrollableLabel {
        height: auto;
    }
    ScrollableLabel > .scrollablelabel--container {
        width: 100%;
        height: auto;
    }
    ScrollableLabel > .scrollablelabel--label {
        width: auto;
        height: auto;
    }
    """
    _texts = var(Text(), always_update=True)
    _global_offset = var(0, always_update=True, init=False)

    def __init__(
        self,
        texts: list[Text] | str | Text | None = None,
        sep: str = " ",
        speed: float = 0.1,
        hold_scroll: bool = False,
        use_mouse_scroll: bool = False,
        mouse_scroll_amount: int = 1,
        auto_scroll: bool = False,
        id: str | None = None,  # noqa: A002
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(id=id, classes=classes, disabled=disabled)
        self._container = Container(classes="scrollablelabel--container")
        self._label = self._Label(classes="scrollablelabel--label")
        self._label.watch_mouse_over = self.watch_mouse_over
        self._container.watch_mouse_over = self.watch_mouse_over
        self._sep = sep
        self._mouse_x = -1
        self._hold_scroll = hold_scroll
        self._use_mouse_scroll = use_mouse_scroll
        self._mouse_scroll_amount = mouse_scroll_amount
        self._auto_scroll = auto_scroll
        self._current_highlighted: TextRange = TextRange(-1, -1)
        self._text_mapping: dict[TextRange, Text] = {}

        if isinstance(texts, list):
            self._generate_mapping(texts, sep)
            self._texts = Text.from_markup(sep)
            self._texts = self._texts.join(texts)
        elif isinstance(texts, (str, Text)):
            text = Text.from_markup(texts) if isinstance(texts, str) else texts
            self._generate_mapping([text], sep)
            self._texts = text

        self._content_width = 0
        self._update_content_width()
        self._scroll_timer = self.set_interval(speed, self._scroll, pause=True)
        if auto_scroll and not use_mouse_scroll:
            self._scroll_timer.resume()

    class _Label(Label):
        class Click(Message):
            def __init__(self, event: events.Click) -> None:
                super().__init__()
                self.event = event

        class MouseMove(Message):
            def __init__(self, event: events.MouseMove) -> None:
                super().__init__()
                self.event = event

        class Leave(Message):
            def __init__(self, event: events.Leave) -> None:
                super().__init__()
                self.event = event

        def on_click(self, event: events.Click) -> None:
            self.post_message(self.Click(event))

        def on_mouse_move(self, event: events.MouseMove) -> None:
            self.post_message(self.MouseMove(event))

        def on_leave(self, event: events.Leave) -> None:
            self.post_message(self.Leave(event))

    class Clicked(Message):
        def __init__(self, widget: "ScrollableLabel", content: Text | None, index: int) -> None:
            super().__init__()
            self.widget = widget
            self.content = content
            self.index = index

    def __rich_repr__(self) -> Result:
        yield "texts", self._texts.plain
        yield "content_width", self.content_width
        yield "container_width", self.container_width
        yield "current_highlighted", f"TextRange({self._current_highlighted.start}, {self._current_highlighted.end})"
        yield "mapping", {f"TextRange({key.start}, {key.end})": value for key, value in self._text_mapping.items()}

    @property
    def content_width(self):
        return self._content_width

    @property
    def container_width(self):
        return self._container.region.width

    def watch__texts(self, value: Text) -> None:
        self._label.update(value)

    def watch__global_offset(self, value: int) -> None:
        if value == 0:
            self.workers.cancel_group(self, "scrollable-label")  # type: ignore
        self._texts = self._new_text_with_offset()
        self._highlight_under_mouse()

    def _update_content_width(self) -> None:
        default = self._default()
        self._content_width = default.cell_len

    def _generate_mapping(self, texts: list[Text], sep: str) -> None:
        self._text_mapping = {}
        start = 0
        for text in texts:
            text_range = TextRange(start, start + text.cell_len)
            start += text.cell_len + Text.from_markup(sep).cell_len
            self._text_mapping[text_range] = text

    def _get_text_from_offset(self, offset: int) -> Text | None:
        if offset < 0:
            return None
        for text_range in self._text_mapping:
            if text_range.within_range(offset + self._global_offset):
                return self._text_mapping[text_range]
        return None

    def _get_index_from_offset(self, offset: int) -> int | None:
        if offset < 0:
            return None
        index = 0
        for text_range in self._text_mapping:
            if text_range.within_range(offset + self._global_offset):
                return index
            index += 1  # noqa: SIM113
        return None

    def _get_range_from_offset(self, offset: int) -> TextRange | None:
        if offset < 0:
            return None
        for text_range in self._text_mapping:
            if text_range.within_range(offset + self._global_offset):
                return text_range
        return None

    def _reset_text(self) -> None:
        self._texts = self._default()

    def _default(self) -> Text:
        return Text(self._sep).join(list(self._text_mapping.values()))

    def _new_text_with_offset(self) -> Text:
        default = self._default()
        text = default.plain
        spans = default.spans
        new_plain = text[self._global_offset :]
        new_spans = [
            Span(max(span.start - self._global_offset, 0), max(span.end - self._global_offset, 0), span.style)
            for span in spans
        ]
        return Text(new_plain, overflow="ellipsis", no_wrap=True, spans=new_spans)

    def _highlight_text_at_offset(self, offset: int) -> None:
        if self._current_highlighted.within_range(offset + self._global_offset):
            return
        text_range = self._get_range_from_offset(offset)
        if text_range:
            self._current_highlighted = text_range
            new_text = self._new_text_with_offset()
            new_text.stylize(
                "underline",
                max(text_range.start - self._global_offset, 0),
                max(text_range.end - self._global_offset, 0),
            )
            self._texts = new_text

    def _highlight_under_mouse(self) -> None:
        text_range = self._get_range_from_offset(self._mouse_x)
        if not text_range:
            return
        self._texts.stylize(
            "underline", max(text_range.start - self._global_offset, 0), max(text_range.end - self._global_offset, 0)
        )

    def update_text(self, text: str | Text) -> None:
        self._global_offset = 0
        text = Text.from_markup(text) if isinstance(text, str) else text
        self._generate_mapping([text], "")
        self._update_content_width()
        self._texts = text

    def update_texts(self, texts: list[Text], sep: str = " ") -> None:
        self._global_offset = 0
        self._sep = sep
        self._generate_mapping(texts, sep)
        self._update_content_width()
        text = Text.from_markup(sep)
        self._texts = text.join(texts)

    def append_text(self, text: str | Text) -> None:
        self._global_offset = 0
        text = Text.from_markup(text) if isinstance(text, str) else text
        self._generate_mapping([*list(self._text_mapping.values()), text], self._sep)
        self._update_content_width()
        self._texts = self._default()

    def set_tooltips(self, string: str | None) -> None:
        self._label.tooltip = string

    def compose(self) -> ComposeResult:
        with self._container:
            yield self._label

    def on__label_click(self, event: _Label.Click) -> None:
        event.stop()
        mouse_event = event.event
        text = self._get_text_from_offset(mouse_event.x)
        index = self._get_index_from_offset(mouse_event.x)
        self.post_message(self.Clicked(self, text, index or -1))

    def on__label_mouse_move(self, event: _Label.MouseMove) -> None:
        event.stop()
        mouse_event = event.event
        self._mouse_x = mouse_event.x
        self._highlight_text_at_offset(mouse_event.x)

    def on__label_leave(self, event: _Label.Leave) -> None:
        event.stop()
        self._current_highlighted = TextRange(-1, -1)
        self._mouse_x = -1
        self._texts = self._new_text_with_offset()
        self._highlight_under_mouse()
        if self._hold_scroll or self._auto_scroll:
            return
        self._global_offset = 0

    def watch_mouse_over(self, value: bool) -> None:
        if self._auto_scroll or self._use_mouse_scroll:
            return
        if self.content_width > self.container_width:
            if value:
                self._scroll_timer.resume()
            else:
                self._scroll_timer.pause()
                if not self._hold_scroll:
                    self._reset_text()

    def on_mouse_scroll_down(self, event: events.MouseDown) -> None:
        if not self._use_mouse_scroll:
            return
        self._global_offset = max(self._global_offset - self._mouse_scroll_amount, 0)

    def on_mouse_scroll_up(self, event: events.MouseUp) -> None:
        if not self._use_mouse_scroll:
            return
        self._global_offset = min(
            self._global_offset + self._mouse_scroll_amount, self.content_width - self.container_width
        )

    def _scroll(self) -> None:
        if self._global_offset < self.content_width:
            self._global_offset += 1
        elif self._hold_scroll or self._auto_scroll:
            self._global_offset = 0


class _DurationCompleteLabel(Static):
    current = reactive(0, layout=True)
    total = reactive(0, layout=True)

    def validate_current(self, value: int | float) -> int:
        if isinstance(value, float):
            return int(value)
        return value

    def validate_total(self, value: int | float) -> int:
        if isinstance(value, float):
            return int(value)
        return value

    def render(self) -> RenderableType:
        m, s = divmod(self.current, 60)
        completed = f"{m:02d}:{s:02d}"

        if self.total != 0:
            m, s = divmod(self.total, 60)
            total = f"{m:02d}:{s:02d}"
            return f"{completed}/{total}"
        return f"{completed}/--:--"


class DurationProgressBar(Widget):
    DEFAULT_CSS = f"""
    DurationProgressBar {{
        width: 1fr;
    }}
    DurationProgressBar ProgressBar Bar {{
        width: 1fr;
    }}
    DurationProgressBar ProgressBar {{
        width: 1fr;
    }}
    DurationProgressBar ProgressBar Bar > .bar--indeterminate {{
        color: {Theme.ACCENT};
    }}
    DurationProgressBar ProgressBar Bar > .bar--bar {{
        color: {Theme.ACCENT};
    }}
    DurationProgressBar _DurationCompleteLabel {{
        width: auto;
        margin: 0 2 0 2;
    }}
    """

    def __init__(self, current: int = 0, total: int = 0, stop: bool = False, pause_on_end: bool = False) -> None:
        super().__init__()
        self.timer = self.set_interval(1, self._update_progress)
        if stop:
            self.timer.pause()
        self.current = current
        self.total = total
        self.pause_on_end = pause_on_end
        self.time_end = 0

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield ProgressBar(show_eta=False, show_percentage=False)
            yield _DurationCompleteLabel()

    def on_mount(self) -> None:
        self.query_one(_DurationCompleteLabel).current = self.current
        self.query_one(_DurationCompleteLabel).total = self.total
        self.query_one(ProgressBar).update(total=self.total if self.total != 0 else None, progress=self.current)

    def _update_progress(self) -> None:
        if self.total != 0 and self.pause_on_end and self.current >= self.total:
            self.timer.pause()
            return
        self.current += 1
        self.query_one(ProgressBar).advance(1)
        self.query_one(_DurationCompleteLabel).current = self.current

    # def update_progress(self, data: ListenWsData):
    #     # TODO: what in the blackmagic fuck
    #     self.time_end = data.song.time_end
    #     if data.song.duration:
    #         self.current = (datetime.now(timezone.utc) - data.start_time).total_seconds()
    #     else:
    #         self.current = 0
    #     self.total = data.song.duration or 0
    #     self.query_one(ProgressBar).update(total=self.total if self.total != 0 else None, progress=self.current)

    def update_progress(self, song: Song) -> None:
        self.time_end = song.time_end
        self.current = 0
        self.query_one(_DurationCompleteLabel).current = self.current
        self.total = song.duration or 0
        self.query_one(_DurationCompleteLabel).total = self.total
        self.query_one(ProgressBar).update(total=self.total if self.total != 0 else None, progress=self.current)

    def pause(self) -> None:
        self.timer.pause()

    def resume(self) -> None:
        self.timer.resume()

    def reset(self) -> None:
        self.current = 0
        self.query_one(ProgressBar).update(total=self.total if self.total != 0 else None, progress=self.current)
        self.query_one(_DurationCompleteLabel).total = self.total


class ExtendedDataTable(DataTable[Any]):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("enter", "select_cursor", "Select", show=False),
        Binding("up,k", "cursor_up", "Cursor Up", show=False),
        Binding("down,j", "cursor_down", "Cursor Down", show=False),
        Binding("right,l", "cursor_right", "Cursor Right", show=False),
        Binding("left,h", "cursor_left", "Cursor Left", show=False),
        Binding("pageup", "page_up", "Page Up", show=False),
        Binding("pagedown", "page_down", "Page Down", show=False),
    ]


class StaticButton(Button):
    DEFAULT_CSS = f"""
    StaticButton {{
        background: {Theme.BUTTON_BACKGROUND};
    }}
    """

    def __init__(
        self,
        label: str | Text | None = None,
        variant: Literal["default", "primary", "success", "warning", "error"] = "default",
        *,
        check_user: bool = False,
        name: str | None = None,
        id: str | None = None,  # noqa: A002
        classes: str | None = None,
        disabled: bool = False,
    ):
        super().__init__(label, variant, name=name, id=id, classes=classes, disabled=disabled)
        self.can_focus = False
        self._check_user = check_user

    async def on_mount(self) -> None:
        if self._check_user:
            client = ListenClient.get_instance()
            if not client.logged_in:
                self.disabled = True


class ToggleButton(StaticButton):
    DEFAULT_CSS = f"""
    ToggleButton.-toggled {{
        background: {Theme.ACCENT};
        text-style: bold reverse;
    }}
    """
    is_toggled: reactive[bool] = reactive(False, init=False, layout=True)

    class Toggled(Message):
        def __init__(self, state: bool) -> None:
            super().__init__()
            self.state = state

    def __init__(
        self,
        label: str | Text | None = None,
        toggled_label: str | Text | None = None,
        variant: Literal["default", "primary", "success", "warning", "error"] = "default",
        *,
        check_user: bool = False,
        name: str | None = None,
        id: str | None = None,  # noqa: A002
        classes: str | None = None,
        disabled: bool = False,
    ):
        super().__init__(label, variant, name=name, id=id, classes=classes, disabled=disabled, check_user=check_user)
        self._default = label
        self._toggled_label = toggled_label

    def watch_is_toggled(self, new: bool) -> None:
        self.toggle_class("-toggled")
        if new and self._toggled_label:
            self.label = self._toggled_label
        else:
            self.label = self._default or ""

    @on(Button.Pressed)
    def toggle_state(self) -> None:
        self.is_toggled = not self.is_toggled
        self.post_message(self.Toggled(self.is_toggled))

    def set_toggle_state(self, state: bool) -> None:
        self.is_toggled = state
        self.post_message(self.Toggled(self.is_toggled))

    def update_toggle_label(self, label: str | Text | None) -> None:
        self._toggled_label = label

    def update_default_label(self, label: str | Text | None) -> None:
        self._default = label


class SongItem(ListItem):
    DEFAULT_CSS = """
    SongItem {
        padding: 1 0 1 0;
    }
    SongItem Label {
        margin-left: 1;
    }
    """

    def __init__(self, song: Song):
        self.song = song
        romaji_first = Config.get_config().display.romaji_first
        title = song.format_title(romaji_first=romaji_first)
        artist = song.format_artists(show_character=False, romaji_first=romaji_first, embed_link=True)
        super().__init__(
            Label(
                Text.from_markup(f"{title}"),
                classes="item-title",
                shrink=True,
            ),
            Label(
                Text.from_markup(f"[{Theme.ACCENT}]{artist}[/]"),
                classes="item-artist",
            ),
        )

    class SongChildClicked(Message):
        """For informing with the parent ListView that we were clicked"""

        def __init__(self, item: "SongItem") -> None:
            self.item = item
            super().__init__()

    async def _on_click(self, _: events.Click) -> None:
        self.post_message(self.SongChildClicked(self))


class ExtendedListView(ListView):
    DEFAULT_CSS = f"""
    ExtendedListView {{
        height: auto;
    }}
    ExtendedListView SongItem {{
        margin-bottom: 1;
        background: {Theme.BACKGROUND};
    }}
    """

    class SongSelected(Message):
        def __init__(self, song: Song) -> None:
            self.song = song
            super().__init__()

    @on(SongItem.SongChildClicked)
    def feed_clicked(self, event: SongItem.SongChildClicked) -> None:
        self.post_message(self.SongSelected(event.item.song))

    def action_select_cursor(self) -> None:
        """Select the current item in the list."""
        selected_child: SongItem | None = self.highlighted_child  # type: ignore
        if selected_child is None:
            return
        self.post_message(self.SongSelected(selected_child.song))
