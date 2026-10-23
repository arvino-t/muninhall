"""Свойства карточек книг в вики: статус чтения (status: read, reading: true) и теги; теги и тема карточек —
в книги приложения (book["vault_tags"], book["vault_topic"]) для графа и фокуса."""
from __future__ import annotations

import re
from datetime import date

from PySide6.QtCore import QObject, Signal

from . import vault as vault_mod


class WikiCards(QObject):
    tags_loaded = Signal(dict)          # {id книги: {"tags", "topic"}} — из фонового потока

    def __init__(self, link, library, parent=None):
        super().__init__(parent)
        self.link = link
        self.library = library
        self.on_tags_loaded: list = []  # кому сообщить, что теги книг обновились (граф, фокус)
        self.tags_loaded.connect(self._apply_tags)

    def _change_card(self, book, decide):
        """decide(свойства карточки) → изменения; пишет их в фоне (CLI может отвечать секунды)."""
        if not self.link.enabled:
            return
        card, v = self.link.card_of(book)
        if not card:
            return
        change = decide(v.card_props(card))
        if change:
            change["updated"] = date.today().isoformat()
            vault_mod.in_background(v.set_props, card, **change)

    def on_finished(self, book, finished: bool):
        """Отметка «Прочитано» в приложении: status: read; снятие отметки возвращает read → indexed.
        Статус ingested (книгу осмыслил LLM) не трогаем."""
        def decide(props):
            status = props.get("status")
            if finished:
                change = {"status": "read"} if status in (None, "indexed") else {}
                if props.get("reading"):
                    change["reading"] = None
                return change
            return {"status": "indexed"} if status == "read" else {}
        self._change_card(book, decide)

    def on_reading(self, book):
        """Книгу начали читать: reading: true (статус indexed не трогаем — его ведёт build_index.py)."""
        if book.get("finished"):
            return
        self._change_card(book, lambda props: {} if props.get("reading") or props.get("status") == "read"
                          else {"reading": True})

    def book_tags(self, book) -> list[str] | None:
        """Теги карточки книги; None — карточки нет (книга вне хранилища)."""
        card, v = self.link.card_of(book)
        if not card:
            return None
        tags = v.card_props(card).get("tags") or []
        return [str(t).lstrip("#") for t in ([tags] if isinstance(tags, str) else tags)]

    def set_book_tags(self, book, tags: list[str]) -> bool:
        card, v = self.link.card_of(book)
        if not card:
            return False
        clean = []
        for t in tags:
            t = re.sub(r"\s+", "-", t.strip().lstrip("#"))
            if t and t not in clean:
                clean.append(t)
        v.set_props(card, tags=clean or None, updated=date.today().isoformat())
        v.forget_tags()
        if clean:
            book["vault_tags"] = clean
        else:
            book.pop("vault_tags", None)
        return True

    def load_tags(self):
        """Теги карточек своих книг (в фоне: карточек сотни) → book["vault_tags"] для графа и фильтров."""
        v = self.link.vault()
        if not v:
            return
        books = [(b["id"], self.library.file_path(b), b.get("title")) for b in self.library.books.values()]
        files = vault_mod.FileVault(v.root)           # читать шапки быстрее файлами, чем через CLI

        def work():
            out = {}
            for bid, path, title in books:
                card = files.find_card(path, title)
                if card:
                    props = files.card_props(card)
                    tags = props.get("tags") or []
                    tags = [tags] if isinstance(tags, str) else tags
                    topic = re.sub(r"^\[\[(?:[^|\]]*\|)?([^\]]*)\]\]$", r"\1", str(props.get("topic") or "")).strip()
                    out[bid] = {"tags": [str(t).lstrip("#") for t in tags if str(t).strip()], "topic": topic}
            self.tags_loaded.emit(out)
        vault_mod.in_background(work)

    def _apply_tags(self, tags: dict):
        for bid, book in self.library.books.items():
            info = tags.get(bid) or {}
            for key, value in (("vault_tags", info.get("tags")), ("vault_topic", info.get("topic"))):
                if value:
                    book[key] = value
                else:
                    book.pop(key, None)
        for cb in list(self.on_tags_loaded):
            cb()

    def all_tags(self) -> list[str]:
        v = self.link.vault()
        return v.all_tags() if v else []
