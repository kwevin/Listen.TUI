from rich.console import RenderableType
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import ProgressBar, Static

from listentui.listen import Song


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
    DEFAULT_CSS = """
    DurationProgressBar {
        height: 1;
        width: 1fr;
    }
    DurationProgressBar ProgressBar Bar {
        width: 1fr;
    }
    DurationProgressBar ProgressBar {
        width: 1fr;
    }
    DurationProgressBar ProgressBar Bar > .bar--indeterminate {
        color: red;
    }
    DurationProgressBar ProgressBar Bar > .bar--bar {
        color: red;
    }
    DurationProgressBar _DurationCompleteLabel {
        width: auto;
        margin-left: 2;
    }
    """

    def __init__(self, current: int = 0, total: int = 0, stop: bool = False, pause_on_end: bool = False) -> None:
        super().__init__()
        self.timer = self.set_interval(1, self._update_progress, pause=stop)
        self.current = current
        self.total = total
        self.pause_on_end = pause_on_end
        self.time_end = 0
        self.progress_bar = ProgressBar(show_eta=False, show_percentage=False)
        self.progress_label = _DurationCompleteLabel()

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield self.progress_bar
            yield self.progress_label

    def on_mount(self) -> None:
        self.progress_label.current = self.current
        self.progress_label.total = self.total
        self.progress_bar.update(total=self.total if self.total != 0 else None, progress=self.current)

    def _update_progress(self) -> None:
        if self.total != 0 and self.pause_on_end and self.current >= self.total:
            self.timer.pause()
            return
        self.current += 1
        self.progress_bar.advance(1)
        self.progress_label.current = self.current

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
        self.progress_label.current = self.current
        self.total = song.duration or 0
        self.progress_label.total = self.total
        self.progress_bar.update(total=self.total if self.total != 0 else None, progress=self.current)

    def update_total(self, total: int) -> None:
        self.total = total
        self.progress_label.total = total
        self.progress_bar.update(total=total, progress=self.current)

    def pause(self) -> None:
        self.timer.pause()

    def resume(self) -> None:
        self.timer.resume()

    def reset(self) -> None:
        self.current = 0
        self.query_one(ProgressBar).update(total=self.total if self.total != 0 else None, progress=self.current)
        self.query_one(_DurationCompleteLabel).total = self.total
