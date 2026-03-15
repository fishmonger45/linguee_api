from typing import ClassVar

import httpx
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Footer, Input, Label, ListItem, ListView, Static

from linguee_api.cache import DiskCache, _cache_key, cached_fetch
from linguee_api.client import CaptchaError, LingueeError, _build_url, fetch_search
from linguee_api.models import Correction, NotFound, ParseError, SearchResult
from linguee_api.parser import parse_search_result
from linguee_api.tui.store import AppState


class ResultsView(Static):
    pass


class DirectionLabel(Static):
    pass


class LingueeApp(App):
    CSS = """
    Screen {
        layout: vertical;
    }
    #search-input {
        dock: top;
        height: 1;
        border: none;
        padding: 0 1;
    }
    #search-input:focus {
        border: none;
    }
    #results-scroll {
        height: 1fr;
        padding: 1 1 0 1;
        scrollbar-size-vertical: 1;
    }
    #results {
        width: 1fr;
    }
    #history-list {
        display: none;
        dock: bottom;
        height: 12;
        border-top: solid $accent;
    }
    #bookmarks-list {
        display: none;
        dock: bottom;
        height: 16;
        border-top: solid $accent;
    }
    #bookmarks-list ListView {
        background: transparent;
    }
    #bookmarks-list ListItem {
        background: transparent;
    }
    #bookmarks-list ListItem:hover {
        background: $surface;
    }
    #bookmarks-header {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    #direction {
        dock: bottom;
        height: 1;
        width: 100%;
        text-align: right;
        padding: 0 1;
        color: $text-muted;
    }
    """

    ENABLE_COMMAND_PALETTE = False

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+o", "go_back", "Back"),
        Binding("ctrl+i", "go_forward", "Fwd"),
        Binding("ctrl+d", "flip_direction", "Flip"),
        Binding("ctrl+s", "toggle_bookmark", "Star"),
        Binding("ctrl+b", "show_bookmarks", "Bookmarks"),
        Binding("ctrl+l", "focus_search", "Search"),
        Binding("escape", "focus_search", "Search", show=False),
        Binding("ctrl+c", "quit", "Quit"),
    ]

    UMLAUT_MAP: ClassVar[dict[str, str]] = {
        "a": "ä",
        "o": "ö",
        "u": "ü",
        "s": "ß",
        "A": "Ä",
        "O": "Ö",
        "U": "Ü",
    }

    def __init__(self) -> None:
        super().__init__()
        self.state = AppState()
        self.http_client: httpx.AsyncClient | None = None
        self.cache = DiskCache()
        self._umlaut_pending = False

    def compose(self) -> ComposeResult:
        yield Input(placeholder="> search...", id="search-input")
        with VerticalScroll(id="results-scroll"):
            yield ResultsView("", id="results")
        yield ListView(id="history-list")
        with Vertical(id="bookmarks-list"):
            yield Label(
                "Bookmarks  (enter to lookup, d to delete)",
                id="bookmarks-header",
            )
            yield ListView(id="bookmarks-items")
        yield DirectionLabel(self._direction_text(), id="direction")
        yield Footer()

    def on_mount(self) -> None:
        self.http_client = httpx.AsyncClient(timeout=10.0)
        self.query_one("#direction", DirectionLabel).update(self._direction_text())
        self.query_one("#search-input", Input).focus()

    async def on_unmount(self) -> None:
        if self.http_client:
            await self.http_client.aclose()

    def _direction_text(self) -> str:
        return f"{self.state.src} → {self.state.dst}"

    def _update_status(self) -> None:
        star = " ★" if self.state.is_bookmarked() else ""
        self.query_one("#direction", DirectionLabel).update(f"{self._direction_text()}{star}")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        word = event.value.strip()
        if not word:
            return
        self._hide_panels()
        self.do_lookup(word)

    async def on_input_changed(self, event: Input.Changed) -> None:
        prefix = event.value.strip()
        history_list = self.query_one("#history-list", ListView)
        if not prefix:
            history_list.display = False
            return
        matches = self.state.search_history(prefix)
        if not matches:
            history_list.display = False
            return
        history_list.clear()
        for m in matches:
            history_list.append(ListItem(Label(m)))
        history_list.display = True

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        list_view = event.list_view
        if list_view.id in ("history-list", "bookmarks-items"):
            word = event.item.query_one(Label).render()
            self._hide_panels()
            inp = self.query_one("#search-input", Input)
            inp.value = str(word)
            self.do_lookup(str(word))

    def _hide_panels(self) -> None:
        self.query_one("#history-list", ListView).display = False
        self.query_one("#bookmarks-list", Vertical).display = False
        self.query_one("#search-input", Input).focus()

    @work(exclusive=True)
    async def do_lookup(self, word: str) -> None:
        results_view = self.query_one("#results", ResultsView)
        results_view.update(Text("...", style="dim"))

        self.state.push_lookup(word)
        self._update_status()

        await self._fetch_and_render(word, results_view)

    async def _fetch_and_render(self, word: str, results_view: ResultsView) -> None:
        try:
            url = _build_url(self.state.src, self.state.dst, word)
            key = _cache_key(url)
            html = await cached_fetch(
                self.cache,
                key,
                lambda: fetch_search(self.http_client, self.state.src, self.state.dst, word),
            )
        except CaptchaError:
            results_view.update(Text("blocked by Linguee (CAPTCHA)", style="bold red"))
            return
        except LingueeError as e:
            results_view.update(Text(f"error: {e.detail}", style="bold red"))
            return
        except httpx.TimeoutException:
            results_view.update(Text("request timed out", style="bold red"))
            return

        result = parse_search_result(html)

        if isinstance(result, NotFound):
            results_view.update(Text("no results", style="dim"))
            return
        if isinstance(result, Correction):
            t = Text()
            t.append("did you mean: ", style="dim")
            t.append(result.text, style="bold underline")
            results_view.update(t)
            self.do_lookup(result.text)
            return
        if isinstance(result, ParseError):
            results_view.update(Text(f"parse error: {result.message}", style="bold red"))
            return

        self._render_results(result)

    def _apply_click(self, line: Text, word: str, start: int) -> None:
        meta = {"@click": f"app.lookup('{self._escape(word)}')"}
        line.apply_meta(meta, start, len(line))

    def _render_results(self, result: SearchResult) -> None:
        parts: list[Text] = []

        for i, lemma in enumerate(result.lemmas):
            if i > 0:
                parts.append(Text("─" * 50, style="dim"))
                parts.append(Text(""))

            header = Text()
            header.append(lemma.text, style="bold")
            if lemma.pos:
                header.append(f"  {lemma.pos}", style="dim")
            if lemma.forms:
                header.append(f"  ({', '.join(lemma.forms)})", style="dim")
            parts.append(header)

            for t in lemma.translations:
                line = Text()
                line.append("  → ", style="cyan")
                start = len(line)
                line.append(t.text)
                self._apply_click(line, t.text, start)
                if t.pos:
                    line.append(f"  {t.pos}", style="dim")
                if t.usage_frequency:
                    dot = " ●" if t.usage_frequency.value == "almost_always" else " ○"
                    line.append(dot, style="green")
                parts.append(line)

                for ex in t.examples:
                    parts.append(Text(f"    {ex.src}"))
                    parts.append(Text(f"    {ex.dst}", style="green"))

        if result.examples:
            parts.append(Text(""))
            parts.append(Text("─" * 50, style="dim"))
            parts.append(Text("Examples", style="bold"))
            parts.append(Text(""))

            for ex in result.examples:
                line = Text()
                line.append("  ")
                start = len(line)
                line.append(ex.text)
                self._apply_click(line, ex.text, start)
                if ex.pos:
                    line.append(f"  {ex.pos}", style="dim")
                translations = ", ".join(t.text for t in ex.translations)
                if translations:
                    line.append("  →  ", style="cyan")
                    line.append(translations)
                parts.append(line)

        combined = Text("\n").join(parts)
        self.query_one("#results", ResultsView).update(combined)

    @staticmethod
    def _escape(s: str) -> str:
        return s.replace("'", "\\'").replace('"', '\\"')

    async def action_lookup(self, word: str) -> None:
        inp = self.query_one("#search-input", Input)
        inp.value = word
        self._hide_panels()
        self.do_lookup(word)

    def action_go_back(self) -> None:
        word = self.state.go_back()
        if word:
            inp = self.query_one("#search-input", Input)
            inp.value = word
            self._hide_panels()
            self.do_lookup(word)

    def action_go_forward(self) -> None:
        word = self.state.go_forward()
        if word:
            inp = self.query_one("#search-input", Input)
            inp.value = word
            self._hide_panels()
            self.do_lookup(word)

    def action_flip_direction(self) -> None:
        self.state.flip_direction()
        self._update_status()
        if self.state.current_word:
            self.do_lookup(self.state.current_word)

    def action_focus_search(self) -> None:
        self._hide_panels()

    def action_toggle_bookmark(self) -> None:
        self.state.toggle_bookmark()
        self._update_status()

    def action_show_bookmarks(self) -> None:
        panel = self.query_one("#bookmarks-list", Vertical)
        if panel.display:
            panel.display = False
            return
        items = self.query_one("#bookmarks-items", ListView)
        items.clear()
        for b in reversed(self.state.bookmarks):
            diff_dir = b.src != self.state.src or b.dst != self.state.dst
            suffix = f"  ({b.src}→{b.dst})" if diff_dir else ""
            items.append(ListItem(Label(f"{b.word}{suffix}")))
        panel.display = True
        items.focus()

    def _active_list(self) -> ListView | None:
        for list_id in ("history-list", "bookmarks-items"):
            lv = self.query_one(f"#{list_id}", ListView)
            if lv.display or (
                list_id == "bookmarks-items" and self.query_one("#bookmarks-list", Vertical).display
            ):
                return lv
        return None

    async def on_key(self, event) -> None:
        if event.key == "ctrl+u":
            self._umlaut_pending = True
            event.prevent_default()
            return

        if self._umlaut_pending:
            self._umlaut_pending = False
            char = event.character or ""
            replacement = self.UMLAUT_MAP.get(char)
            if replacement:
                inp = self.query_one("#search-input", Input)
                inp.insert_text_at_cursor(replacement)
                event.prevent_default()
                return

        if event.key in ("ctrl+n", "ctrl+p"):
            lv = self._active_list()
            if lv is not None:
                if event.key == "ctrl+n":
                    lv.action_cursor_down()
                else:
                    lv.action_cursor_up()
                lv.focus()
                event.prevent_default()
                return

        bookmarks_panel = self.query_one("#bookmarks-list", Vertical)
        if bookmarks_panel.display and event.key == "d":
            items = self.query_one("#bookmarks-items", ListView)
            if items.highlighted_child is not None:
                label_text = str(items.highlighted_child.query_one(Label).render())
                word = label_text.split("  (")[0]
                self.state.toggle_bookmark(word)
                items.remove_children([items.highlighted_child])
                if not self.state.bookmarks:
                    bookmarks_panel.display = False
