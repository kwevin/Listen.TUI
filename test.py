from __future__ import annotations

import asyncio
import queue
from collections import deque
from dataclasses import dataclass
from typing import Any, ClassVar, Iterable, Literal, Never, NewType, Optional, Tuple, Union

from rich import pretty, style
from rich.cells import cached_cell_len
from rich.console import RenderableType
from rich.pretty import Pretty, pretty_repr
from rich.repr import Result
from rich.text import Span, Text
from textual import events, on, work, worker
from textual.app import ComposeResult, RenderResult
from textual.binding import Binding, BindingType
from textual.color import Lab
from textual.containers import Container, Grid, Horizontal
from textual.coordinate import Coordinate
from textual.message import Message
from textual.reactive import Reactive, reactive, var
from textual.screen import ModalScreen, Screen
from textual.widget import Widget
from textual.widgets import Button, DataTable, Label, ListItem, ListView, ProgressBar, RichLog, Static

from listentui.listen.client import ListenClient
from listentui.listen.types import Song
from listentui.utilities import format_time_since


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

    def __repr__(self) -> str:
        return f"TextRange({self.start}, {self.end})"

    def __rich_repr__(self) -> Result:
        yield "TextRange", f"{self.start}, {self.end}"

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
        self._current_highlighted = TextRange(-1, -1)
        self._remove_underline()

        if self._max_scroll == -1:
            return
        if not self._auto_return:
            return
        if self._can_scroll:
            self.reset()
        self._offset = self._offset

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


class SongScreen(Screen[bool]):
    """Screen for displaying Song details"""

    DEFAULT_CSS = """
    SongScreen {
        align: center middle;
        background: $background;
    }
    SongScreen ScrollableLabel {
        height: 1;
    }
    SongScreen #artist {
        color: red;
    }
    SongScreen Grid {
        grid-size: 3 4;
        grid-gutter: 1 2;
        grid-rows: 1 3 2 1fr;
        padding: 0 2;
        width: 96;
        height: 14;
        border: thick $background 80%;
        background: $surface;
    }
    SongScreen > Container {
        height: 3;
        width: 100%;
        align: left middle;
    }
    SongScreen Horizontal {
        column-span: 3;
        width: 100%;
        align: center middle;
    }
    SongScreen Horizontal > * {
        margin-right: 1;
    }
    SongScreen StaticButton {
        min-width: 13;
    }
    SongScreen #favorite {
        min-width: 14;
    }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "cancel"),
    ]

    def __init__(self, song: Song, favorited: bool = False):
        super().__init__()
        self.song = song
        self.is_favorited = favorited

    def compose(self) -> ComposeResult:
        with Grid():
            yield Label("Track/Artist")
            yield Label("Album")
            yield Label("Source")
            yield Container(
                ScrollableLabel(Text.from_markup(self.song.format_title(romaji_first=False) or ""), id="title"),
                ScrollableLabel(
                    *[Text.from_markup(artist) for artist in a]
                    if (a := self.song.format_artists_list(romaji_first=False)) is not None
                    else [],
                    id="artist",
                ),
            )
            yield Container(
                ScrollableLabel(Text.from_markup(self.song.format_album(romaji_first=False) or ""), id="album")
            )
            yield Container(
                ScrollableLabel(Text.from_markup(self.song.format_source(romaji_first=False) or ""), id="source")
            )
            yield Label(f"Duration: {self.song.duration}", id="duration")
            yield Label(
                f"Last played: {format_time_since(self.song.last_played, True) if self.song.last_played else None}",
                id="last_play",
            )
            yield Label(f"Time played: {self.song.played}", id="time_played")
            with Horizontal(id="horizontal"):
                yield Button("Preview", id="preview")
                yield ProgressBar(total=0)
                yield Button("Favorite", id="favorite")
                yield Button("Request", id="request")

    async def on_scrollable_label_clicked(self, event: ScrollableLabel.Clicked) -> None:  # noqa: PLR0911
        container_id = event.widget.id
        client = ListenClient.get_instance()
        if not container_id:
            return
        match container_id:
            case "artist":
                if not self.song.artists:
                    return
                if len(self.song.artists) == 1:
                    artist = await client.artist(self.song.artists[0].id)
                    if not artist:
                        return
                    self.notify("Pushing artist screen")
                else:
                    artist = await client.artist(self.song.artists[event.index].id)
                    if not artist:
                        raise Exception("Cannot be no artist")
                    self.notify("Pushing artist screen")
            case "album":
                if not self.song.album:
                    return
                album = await client.album(self.song.album.id)
                if not album:
                    return
                self.notify("Pushing album screen")
            case "source":
                if not self.song.source:
                    return
                source = await client.source(self.song.source.id)
                if not source:
                    return
                self.notify("Pushing source screen")
            case _:
                return


if __name__ == "__main__":
    from textual.app import App, ComposeResult

    class MyApp(App[None]):
        DEFAULT_CSS = """
        """

        def compose(self) -> ComposeResult:
            yield Label("Click!")

        @work
        async def on_click(self) -> None:
            client = ListenClient.get_instance()
            song = await client.song(14949)
            await self.push_screen_wait(SongScreen(song))

    app = MyApp()
    app.run()
