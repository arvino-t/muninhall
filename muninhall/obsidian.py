"""Хранилище Obsidian: связь с ним (VaultLink) и страницы выделений (HighlightPages).
Статус и теги в карточках — wiki_cards.py, страница фокуса — focus_page.py.

Страница выделений книги — `wiki/highlights/<Книга>.md`. Приложение переписывает только свой блок между
метками BLOCK_START/BLOCK_END; всё, что пользователь написал вне блока, остаётся. Карточку источника
не трогаем ради выделений: страница ссылается на неё (`sources:`), и Obsidian показывает связь в обратных
ссылках карточки.
"""
from __future__ import annotations

import re
import time
from datetime import date
from pathlib import Path

from PySide6.QtCore import QObject, QTimer

from . import vault as vault_mod
from .core import log
from .highlights import COLORS, color_names
from .i18n import tr

BLOCK_START = "<!-- muninhall:highlights -->"
BLOCK_END = "<!-- /muninhall:highlights -->"
HIGHLIGHTS_DIR = "wiki/highlights"


def safe_name(title: str, limit=120) -> str:
    """Имя файла из названия книги: без символов, запрещённых в Obsidian и файловых системах."""
    name = re.sub(r'[\\/:*?"<>|#^\[\]]+', " ", title or "").strip(" .")
    return re.sub(r"\s+", " ", name)[:limit].strip() or tr("Без названия")


def color_tag(name: str) -> str:
    return "#" + re.sub(r"\s+", "-", name.strip().lower())


def book_link(book_id: str, hid: str) -> str:
    return f"muninhall://open?book={book_id}&hl={hid}"


def render_block(book: dict, highlights: list[dict], names: dict[str, str]) -> str:
    """Блок приложения: цитаты по главам, заметка, метка смысла, ссылка в книгу."""
    lines = [BLOCK_START,
             tr("<!-- Этот блок обновляет Muninhall: правки внутри него перезапишутся. "
                "Пишите свои мысли выше или ниже блока. -->")]
    if not highlights:
        lines.append(tr("_Выделений пока нет._"))
    chapter = None
    for h in highlights:
        ch = (h.get("chapter") or "").strip()
        if ch != chapter:
            chapter = ch
            lines += ["", f"## {ch}" if ch else f"## {tr('Без главы')}"]
        lines.append("")
        quote = re.sub(r"\s+", " ", h.get("text") or "").strip()
        lines.append(f"> {quote}")
        note = (h.get("note") or "").strip()
        if note:
            lines += ["", *(f"{ln}" if ln.strip() else "" for ln in note.split("\n"))]
        meta = color_tag(names.get(h.get("color"), names[COLORS[0]]))
        lines.append("")
        lines.append(f"{meta} · [{tr('в книге')}]({book_link(book['id'], h['id'])})")
    lines.append(BLOCK_END)
    return "\n".join(lines)


def merge_page(existing: str | None, header: dict, block: str) -> str:
    """Новая страница или старая с заменённым блоком приложения и обновлённой шапкой."""
    if existing is None:
        text = "---\n---\n# " + header["title"] + "\n\n" + block + "\n"
        return vault_mod.set_frontmatter(text, **header)
    start, end = existing.find(BLOCK_START), existing.find(BLOCK_END)
    if start != -1 and end != -1 and end > start:
        text = existing[:start] + block + existing[end + len(BLOCK_END):]
    else:                                  # блок удалили руками — добавляем в конец, текст пользователя цел
        text = existing.rstrip("\n") + "\n\n" + block + "\n"
    keep = {k: v for k, v in header.items() if k != "created"}
    if "created" not in vault_mod.parse_frontmatter(existing):
        keep["created"] = header["created"]
    return vault_mod.set_frontmatter(text, **keep)


class VaultLink:
    """Связь с хранилищем Obsidian: подключение (CLI или файлы, перепроверяется не чаще раза в 30 с),
    карточка книги, названия цветов выделений. Только настройки и библиотека — без остального приложения."""

    def __init__(self, settings, library):
        self.settings = settings
        self.library = library
        self._vault = None
        self._vault_at = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.settings.get("obsidianExport", True))

    def vault(self, fresh=False):
        if fresh or self._vault is None or time.monotonic() - self._vault_at > 30:
            self._vault = vault_mod.connect(self.settings)
            self._vault_at = time.monotonic()
        return self._vault

    def names(self) -> dict[str, str]:
        custom = self.settings.get("highlightColors") or {}
        base = color_names()
        return {k: (custom.get(k) or base[k]) for k in COLORS}

    def card_of(self, book):
        """(карточка книги или None, хранилище или None)."""
        v = self.vault()
        path = self.library.file_path(book)
        return (v.find_card(path, book.get("title")) if v else None), v


class HighlightPages(QObject):
    """Страницы выделений `wiki/highlights/<Книга>.md`: выгрузка через 2 с после изменения выделений."""

    def __init__(self, link: VaultLink, library, highlights, parent=None):
        super().__init__(parent)
        self.link = link
        self.library = library
        self.highlights = highlights
        self._pending: set[str] = set()
        self._timer = QTimer(self, singleShot=True, interval=2000)
        self._timer.timeout.connect(self.export_pending)
        highlights.changed.connect(self.schedule)

    def schedule(self, book_id: str):
        if self.link.enabled:
            self._pending.add(book_id)
            self._timer.start()

    def export_pending(self):
        ids, self._pending = self._pending, set()
        for bid in ids:
            book = self.library.books.get(bid)
            if book:
                self.export_book(book)

    def export_all(self) -> int:
        """Все книги с выделениями; число выгруженных страниц."""
        return sum(1 for b in self.highlights.books_with_highlights() if self.export_book(b))

    def page_rel(self, book, card) -> str:
        stem = card.stem if card else safe_name(book.get("title") or "")
        return f"{HIGHLIGHTS_DIR}/{stem}.md"

    def export_book(self, book) -> bool:
        card, v = self.link.card_of(book)
        if not v:
            return False
        items = self.highlights.for_book(book)
        rel = self.page_rel(book, card)
        existing = v.read_page(rel)
        if existing is None and not items:
            return False                    # выделений нет и страницы не было — ничего не создаём
        today = date.today().isoformat()
        card_props = v.card_props(card) if card else {}
        # название и авторы — из карточки, если она есть (там они выверены), иначе из библиотеки
        header = {"type": "highlights", "title": str(card_props.get("title") or book.get("title") or Path(rel).stem)}
        authors = card_props.get("authors") or ", ".join(book.get("authors") or [])
        if authors:
            header["authors"] = authors if isinstance(authors, str) else ", ".join(map(str, authors))
        if card:
            header["sources"] = [v.card_link(card)]
        path = self.library.file_path(book)
        rel_file = v.rel_of(path) if path else None
        if rel_file:
            header["file"] = rel_file
        header.update(created=today, updated=today)
        text = merge_page(existing, header, render_block(book, items, self.link.names()))
        if text == existing:
            return False
        try:
            v.write_page(rel, text)
            if existing is None:
                v.append_log(f"## [{today}] highlights | {header['title']}")
        except OSError as e:
            log("выгрузка выделений не удалась:", rel, e)
            return False
        return True

    def open_page(self, book) -> str | None:
        """obsidian:// ссылка на страницу выделений книги (если она есть)."""
        card, v = self.link.card_of(book)
        if not v:
            return None
        rel = self.page_rel(book, card)
        return v.obsidian_uri(rel) if v.read_page(rel) is not None else None
