from typing import Any, ClassVar, Iterable, Literal, Tuple

from rich.cells import cached_cell_len
from rich.console import RenderableType
from rich.repr import Result
from rich.text import Span, Text
from textual import events, on
from textual.app import ComposeResult, RenderResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal
from textual.message import Message
from textual.reactive import reactive, var
from textual.widget import Widget
from textual.widgets import Button, DataTable, Label, ListItem, ListView, ProgressBar, Static

from listentui.data import Config, Theme
from listentui.listen import ListenClient, Song


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
        width: 100%;
        height: 1;
    }
    """
    text = reactive(Text, always_update=True, layout=True)
    _offset = var(0, always_update=True, init=False)
    _mouse_pos = var(-1, always_update=True, init=False)

    class Clicked(Message):
        def __init__(self, widget: "ScrollableLabel", content: Text, index: int) -> None:
            super().__init__()
            self.widget = widget
            self.content = content
            self.index = index

    def __init__(
        self,
        *texts: Text,
        sep: str = ", ",
        can_scroll: bool = True,
        speed: float = 0.1,
        use_mouse_scroll: bool = False,
        mouse_scroll_amount: int = 1,
        auto_return: bool = True,
        return_delay: float = 2.5,
        return_speed: float = 0.05,
        id: str | None = None,  # noqa: A002
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(id=id, classes=classes, disabled=disabled)

        self._original = list(texts)
        self._sep = sep
        self._can_scroll = can_scroll
        self._auto_return = auto_return
        self._return_delay = return_delay
        self._use_mouse_scroll = use_mouse_scroll
        self._mouse_scroll_amount = mouse_scroll_amount

        self._text_mapping: dict[TextRange, Tuple[Text, int]] = {}
        self._text_cell_mapping: dict[TextRange, TextRange] = {}
        self._current_highlighted = TextRange(-1, -1)
        self._cell_offset = 0
        self._cell_map: dict[str, int] = {}
        self._min_scroll = 0
        self._max_scroll = -1
        self._is_scrolling = False

        self._scroll_timer = self.set_interval(speed, self._scroll, pause=True)
        self._unscroll_timer = self.set_interval(return_speed, self._unscroll, pause=True)

    def __rich_repr__(self) -> Result:
        yield "text", self.text.plain
        yield "offset", self._offset
        yield "cell_offset", self._cell_offset
        yield "min_scroll", self._min_scroll
        yield "max_scroll", self._max_scroll
        yield "current_highlighted", f"TextRange({self._current_highlighted.start}, {self._current_highlighted.end})"
        yield "is_scrolling", self._is_scrolling
        yield "mouse_pos", self._mouse_pos
        yield "mapping", {f"TextRange({key.start}, {key.end})": value for key, value in self._text_mapping.items()}
        yield (
            "cell_mapping",
            {
                f"TextRange({key.start}, {key.end})": f"TextRange({value.start}, {value.end})"
                for key, value in self._text_cell_mapping.items()
            },
        )
        yield "spans", self.text.spans

    def render(self) -> RenderResult:
        return self.text

    def resume(self) -> None:
        """scroll the text if it's not scrolling already"""
        if self._is_scrolling:
            return
        self._is_scrolling = True
        self._scroll_timer.resume()

    def reset(self, delay: float | None = None) -> None:
        """reset the text to its original position after delay, default is return_delay"""
        self._scroll_timer.pause()
        self._is_scrolling = False

        self.set_timer(delay or self._return_delay, self._unscroll_can_resume)

    def update(self, *texts: Text) -> None:
        """update the text with new texts"""
        self._update_text(texts)

    def append(self, text: Text) -> None:
        """append text to the end of the text"""
        self._update_text([*self._original, text])

    def _update_text(self, texts: Iterable[Text]) -> None:
        self.text = Text(self._sep, overflow="ellipsis", no_wrap=True).join(texts)
        self._original = list(texts)
        self._update_cell_map(self.text)
        self._update_mapping(texts, self._sep)
        self._calculate_scrollable_amount()
        self._highlight_under_mouse()

    def _watch__offset(self, value: int) -> None:
        self._cell_offset = self._get_cell_offset(value)
        default = self._default()
        text = default.plain
        spans = default.spans
        new_plain = text[self._offset :]
        new_spans = [
            Span(max(span.start - self._offset, 0), max(span.end - self._offset, 0), span.style) for span in spans
        ]
        self.text = Text(new_plain, overflow="ellipsis", no_wrap=True, spans=new_spans)
        self._highlight_under_mouse(forced=True)

    def _watch__mouse_pos(self, _: int) -> None:
        if self._mouse_pos == -1:
            return
        self._highlight_under_mouse()

    def _watch_text(self, old: Text, new: Text) -> None:
        self.log.debug(f"{old} ==> {new}")

    def _get_range_from_offset(self, offset: int) -> TextRange | None:
        if offset < 0:
            return None
        for cell_range, text_range in self._text_cell_mapping.items():
            if cell_range.within_range(offset + self._cell_offset):
                return text_range
        return None

    def _highlight_under_mouse(self, forced: bool = False) -> None:
        if self._mouse_pos == -1:
            return
        text_range = self._get_range_from_offset(self._mouse_pos)
        if not text_range:
            if self._current_highlighted != TextRange(-1, -1):
                self._remove_underline()
            return
        if self._current_highlighted == text_range and not forced:
            return
        self._current_highlighted = text_range
        start = max(text_range.start - self._offset, 0)
        end = max(text_range.end - self._offset, 0)
        # self.notify(f"{start = }, {end = }")
        spans = [*self._strip_underline(self.text.spans), Span(start, end, "underline")]
        self.text = Text(self.text.plain, overflow="ellipsis", no_wrap=True, spans=spans)

    def _strip_underline(self, spans: Iterable[Span]) -> list[Span]:
        return [span for span in spans if span.style != "underline"]

    def _remove_underline(self):
        self._current_highlighted = TextRange(-1, -1)
        self.text = Text(
            self.text.plain, overflow="ellipsis", no_wrap=True, spans=self._strip_underline(self.text.spans)
        )

    def _reset_state(self) -> None:
        self._scroll_timer.pause()
        self._unscroll_timer.pause()
        self._offset = 0
        self._is_scrolling = False
        self._current_highlighted = TextRange(-1, -1)
        self._update_text(self._original)

    def _on_resize(self, event: events.Resize) -> None:
        self._reset_state()

    def _calculate_scrollable_amount(self) -> None:
        default = self._default()
        container_width_cell = self.container_size.width
        if container_width_cell <= 0:
            self._max_scroll = -1
            return

        text_width_cell = default.cell_len
        if container_width_cell > text_width_cell:
            self._max_scroll = -1
            return

        scrollable_cell = text_width_cell - container_width_cell
        cell_total = 0
        count = 0

        for index, char in enumerate(default.plain):
            cell_total += self._cell_map[char]
            count = index

            if cell_total > scrollable_cell:
                break

        self._max_scroll = count

    def _default(self) -> Text:
        return Text(self._sep).join(self._original)

    def _update_cell_map(self, text: Text) -> None:
        self._cell_map = {char: cached_cell_len(char) for char in text.plain}

    def _get_cell_offset(self, offset: int) -> int:
        if offset < 0:
            return 0
        return sum(self._cell_map[char] for char in self._default().plain[:offset])

    def _update_mapping(self, texts: Iterable[Text], sep: str) -> None:
        self._text_mapping = {}
        self._text_cell_mapping = {}
        start = 0
        start_cell = 0
        sep_len = len(Text.from_markup(sep))
        sep_cell = Text.from_markup(sep).cell_len
        for idx, text in enumerate(texts):
            text_len = len(text)
            text_range = TextRange(start, start + text_len)
            text_cell = TextRange(start_cell, start_cell + text.cell_len)
            start += text_len + sep_len
            start_cell += text.cell_len + sep_cell
            self._text_cell_mapping[text_cell] = text_range
            self._text_mapping[text_range] = text, idx

    def _on_mouse_move(self, event: events.MouseMove) -> None:
        self._mouse_pos = event.x

        if self._max_scroll == -1:
            return
        if self._is_scrolling:
            return
        if self._use_mouse_scroll:
            return
        if self._can_scroll:
            self.resume()

    def on_click(self, event: events.Click) -> None:
        if self._current_highlighted == TextRange(-1, -1):
            return
        content = self._text_mapping.get(self._current_highlighted)
        if not content:
            return

        self.post_message(self.Clicked(self, content[0], content[1]))

    def _on_leave(self, event: events.Leave) -> None:
        self.log.debug("event: _on_leave")
        self._mouse_pos = -1

        if self._current_highlighted != TextRange(-1, -1):
            self._current_highlighted = TextRange(-1, -1)
            self._remove_underline()

        if self._max_scroll == -1:
            return
        if not self._auto_return:
            return
        if self._can_scroll:
            self.reset()
        # self._offset = self._offset

    def _on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        if self._max_scroll == -1:
            return
        if not self._use_mouse_scroll:
            return
        if not self._can_scroll:
            return
        self._offset = max(self._offset - self._mouse_scroll_amount, 0)

    def _on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        if self._max_scroll == -1:
            return
        if not self._use_mouse_scroll:
            return
        if not self._can_scroll:
            return
        self._offset = min(self._offset + self._mouse_scroll_amount, self._max_scroll)

    async def _scroll(self) -> None:
        self._unscroll_timer.pause()
        if self._offset < self._max_scroll:
            self._offset += 1
        else:
            self._scroll_timer.pause()
            self._is_scrolling = False

    async def _unscroll(self) -> None:
        if self._is_scrolling:
            return
        if self._offset > self._min_scroll:
            self._offset -= 1
        else:
            self._unscroll_timer.pause()

    def _unscroll_can_resume(self) -> None:
        if self._is_scrolling:
            return
        if self._mouse_pos != -1:
            return
        self._unscroll_timer.resume()


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
