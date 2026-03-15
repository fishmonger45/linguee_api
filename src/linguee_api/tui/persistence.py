import json
from pathlib import Path

from pydantic import BaseModel

MAX_HISTORY = 500


class HistoryEntry(BaseModel):
    word: str
    src: str
    dst: str


class BookmarkEntry(BaseModel):
    word: str
    src: str
    dst: str


def data_dir() -> Path:
    d = Path.home() / ".local" / "share" / "linguee"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_history() -> list[HistoryEntry]:
    p = data_dir() / "history.json"
    if not p.exists():
        return []
    try:
        return [HistoryEntry(**e) for e in json.loads(p.read_text())]
    except (json.JSONDecodeError, KeyError):
        return []


def save_history(entries: list[HistoryEntry]) -> None:
    entries = entries[-MAX_HISTORY:]
    p = data_dir() / "history.json"
    p.write_text(json.dumps([e.model_dump() for e in entries], ensure_ascii=False, indent=2))


def load_bookmarks() -> list[BookmarkEntry]:
    p = data_dir() / "bookmarks.json"
    if not p.exists():
        return []
    try:
        return [BookmarkEntry(**e) for e in json.loads(p.read_text())]
    except (json.JSONDecodeError, KeyError):
        return []


def save_bookmarks(entries: list[BookmarkEntry]) -> None:
    p = data_dir() / "bookmarks.json"
    p.write_text(json.dumps([e.model_dump() for e in entries], ensure_ascii=False, indent=2))
