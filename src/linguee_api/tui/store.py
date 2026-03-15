from linguee_api.tui.persistence import (
    BookmarkEntry,
    HistoryEntry,
    load_bookmarks,
    load_history,
    save_bookmarks,
    save_history,
)


def _matches(entry: HistoryEntry | BookmarkEntry, word: str, src: str, dst: str) -> bool:
    return entry.word == word and entry.src == src and entry.dst == dst


class AppState:
    def __init__(self) -> None:
        self.src = "de"
        self.dst = "en"
        self.history: list[HistoryEntry] = load_history()
        self.bookmarks: list[BookmarkEntry] = load_bookmarks()
        self.nav_stack: list[str] = []
        self.nav_index: int = -1
        self.current_word: str = ""

    def push_lookup(self, word: str) -> None:
        if self.nav_index < len(self.nav_stack) - 1:
            self.nav_stack = self.nav_stack[: self.nav_index + 1]
        self.nav_stack.append(word)
        self.nav_index = len(self.nav_stack) - 1
        self.current_word = word

        entry = HistoryEntry(word=word, src=self.src, dst=self.dst)
        self.history = [h for h in self.history if not _matches(h, word, self.src, self.dst)]
        self.history.append(entry)
        save_history(self.history)

    def go_back(self) -> str | None:
        if self.nav_index <= 0:
            return None
        self.nav_index -= 1
        self.current_word = self.nav_stack[self.nav_index]
        return self.current_word

    def go_forward(self) -> str | None:
        if self.nav_index >= len(self.nav_stack) - 1:
            return None
        self.nav_index += 1
        self.current_word = self.nav_stack[self.nav_index]
        return self.current_word

    def flip_direction(self) -> tuple[str, str]:
        self.src, self.dst = self.dst, self.src
        return self.src, self.dst

    def toggle_bookmark(self, word: str | None = None) -> bool:
        word = word or self.current_word
        if not word:
            return False
        is_existing = any(_matches(b, word, self.src, self.dst) for b in self.bookmarks)
        if is_existing:
            self.bookmarks = [
                b for b in self.bookmarks if not _matches(b, word, self.src, self.dst)
            ]
            save_bookmarks(self.bookmarks)
            return False
        self.bookmarks.append(BookmarkEntry(word=word, src=self.src, dst=self.dst))
        save_bookmarks(self.bookmarks)
        return True

    def is_bookmarked(self, word: str | None = None) -> bool:
        word = word or self.current_word
        return any(_matches(b, word, self.src, self.dst) for b in self.bookmarks)

    def search_history(self, query: str) -> list[str]:
        query_lower = query.lower()
        seen: set[str] = set()
        results: list[str] = []
        for entry in reversed(self.history):
            if (
                entry.src == self.src
                and entry.dst == self.dst
                and _fuzzy_match(query_lower, entry.word.lower())
                and entry.word not in seen
            ):
                seen.add(entry.word)
                results.append(entry.word)
        return results[:20]


def _fuzzy_match(query: str, target: str) -> bool:
    qi = 0
    for char in target:
        if qi < len(query) and char == query[qi]:
            qi += 1
    return qi == len(query)
