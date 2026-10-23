"""Выделения и заметки в книгах.

Выделение — цитата с местом в книге (раздел, CFI и окружение цитаты, чтобы найти её снова даже без CFI,
например в PDF), цветом-смыслом и заметкой. Хранение как у места чтения: выделения своих книг — в
хранилище их библиотеки `<корень>/.library/highlights.json` (ключ — путь книги в библиотеке, едут вместе
с папкой), книг ЛитРес и открытых файлов — в данных приложения (highlights.json).
"""
from __future__ import annotations

import time
import uuid

from PySide6.QtCore import QObject, QTimer, Signal

from .core import HIGHLIGHTS_FILE, STORE_HIGHLIGHTS, load_json, save_json

# Цвет — смысл выделения: от него зависят метки в Obsidian, а дальше — напоминания и «куда вернуться»
COLORS = ("important", "advice", "concept", "question")
FIELDS = ("section", "cfi", "text", "prefix", "suffix", "color", "note", "chapter", "fraction")


def color_names() -> dict[str, str]:
    from .i18n import tr
    return {"important": tr("Важное"), "advice": tr("Совет"), "concept": tr("Понятие"), "question": tr("Вопрос")}


class HighlightStore(QObject):
    changed = Signal(str)         # id книги, у которой изменились выделения

    def __init__(self, library, app_file=HIGHLIGHTS_FILE, parent=None):
        super().__init__(parent)
        self.library = library
        self.app_file = app_file
        self._app: dict[str, list] | None = None          # {id книги: [выделения]}
        self._libs: dict[str, dict[str, list]] = {}        # {id библиотеки: {путь книги: [выделения]}}
        self._dirty: set[str] = set()                      # "app" или id библиотеки
        self._timer = QTimer(self, singleShot=True, interval=1500)
        self._timer.timeout.connect(self.flush)

    # --- где лежат выделения книги

    def _slot(self, book) -> tuple[str, dict, str]:
        """(куда писать, словарь выделений, ключ книги в нём)."""
        lib_id = book.get("library") if book.get("source") == "folder" else None
        info = self.library.folder_libs.get(lib_id) if lib_id else None
        if info and book.get("rel"):
            if lib_id not in self._libs:
                data = self.library.store.read_folder_store(info["store"], STORE_HIGHLIGHTS) or {}
                self._libs[lib_id] = data.get("books", {}) if isinstance(data, dict) else {}
            return lib_id, self._libs[lib_id], book["rel"]
        if self._app is None:
            data = load_json(self.app_file, {})
            self._app = data.get("books", {}) if isinstance(data, dict) else {}
        return "app", self._app, book["id"]

    # --- чтение

    def for_book(self, book) -> list[dict]:
        """Выделения книги в порядке чтения (по разделу и месту в книге)."""
        _where, data, key = self._slot(book)
        return sorted(data.get(key, []), key=lambda h: (h.get("section") or 0, h.get("fraction") or 0,
                                                       h.get("created") or 0))

    def get(self, book, hid) -> dict | None:
        return next((h for h in self.for_book(book) if h["id"] == hid), None)

    def books_with_highlights(self) -> list[dict]:
        """Книги, у которых есть выделения (для выгрузки всего разом)."""
        return [b for b in self.library.books.values() if self.for_book(b)]

    # --- изменение

    def add(self, book, **fields) -> dict:
        now = time.time()
        h = {"id": uuid.uuid4().hex[:12], "created": now, "updated": now,
             **{k: fields.get(k) for k in FIELDS}}
        if h["color"] not in COLORS:
            h["color"] = COLORS[0]
        h["note"] = h["note"] or ""
        where, data, key = self._slot(book)
        data.setdefault(key, []).append(h)
        self._touch(where, book)
        return h

    def update(self, book, hid, **fields) -> dict | None:
        where, data, key = self._slot(book)
        for h in data.get(key, []):
            if h["id"] == hid:
                h.update({k: v for k, v in fields.items() if k in FIELDS})
                h["updated"] = time.time()
                self._touch(where, book)
                return h
        return None

    def remove(self, book, hid) -> bool:
        where, data, key = self._slot(book)
        items = data.get(key, [])
        left = [h for h in items if h["id"] != hid]
        if len(left) == len(items):
            return False
        if left:
            data[key] = left
        else:
            data.pop(key, None)
        self._touch(where, book)
        return True

    def _touch(self, where, book):
        self._dirty.add(where)
        self._timer.start()
        self.changed.emit(book["id"])

    # --- запись

    def flush(self):
        self._timer.stop()
        for where in sorted(self._dirty):
            if where == "app":
                save_json(self.app_file, {"version": 1, "books": self._app or {}})
            elif where in self.library.folder_libs:
                self.library.store.write_folder_store(self.library.folder_libs[where]["store"], STORE_HIGHLIGHTS,
                                                      {"version": 1, "books": self._libs.get(where, {})})
        self._dirty.clear()
