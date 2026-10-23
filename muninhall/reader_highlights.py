"""Выделения в читалке: список цитат книги (кнопка в шапке), меню выделения, окно заметки.

Страница книги (web/reader.js) рисует выделения и присылает «highlight-add» / «highlight-menu»;
этот объект хранит их через app.highlights и отдаёт странице обновлённый список.
"""
from __future__ import annotations

import json

from PySide6.QtCore import QObject, Qt, QUrl
from PySide6.QtGui import QColor, QCursor, QDesktopServices, QGuiApplication, QIcon, QPixmap
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu, QPlainTextEdit,
                               QPushButton, QVBoxLayout, QWidget)

from .highlights import COLORS
from .i18n import tr
from .widgets import IconButton, Popover, attach_popover, cls, exec_dialog, frameless_dialog

# те же цвета, что в reader.js (HL_COLORS)
RGB = {"important": (255, 196, 0), "advice": (76, 190, 80), "concept": (66, 145, 255), "question": (240, 98, 170)}


def color_icon(color: str, size=14) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(QColor(*RGB.get(color, RGB["important"])))
    return QIcon(pm)


class ReaderHighlights(QObject):
    def __init__(self, reader):
        super().__init__(reader)
        self.reader = reader
        self.app = reader.app
        self.book = reader.book
        self.button = IconButton("format-text-highlight", tr("Выделения"))
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setMinimumSize(380, 360)
        self.list.setWordWrap(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.itemClicked.connect(self._on_item)
        self.empty = QLabel(tr("Выделите текст в книге — появится панель с цветами и заметкой."))
        self.empty.setWordWrap(True)
        cls(self.empty, "dim")
        self.obsidian_btn = QPushButton(tr("Открыть в Obsidian"))
        self.obsidian_btn.clicked.connect(self._open_obsidian)
        v.addWidget(self.list, 1)
        v.addWidget(self.empty)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(self.obsidian_btn)
        v.addLayout(row)
        self.popover = Popover(box)
        attach_popover(self.button, self.popover)
        self.button.clicked.connect(self.fill)
        self.app.highlights.changed.connect(self._on_changed)

    # --- данные

    def items(self) -> list[dict]:
        return self.app.highlights.for_book(self.book)

    def names(self) -> dict[str, str]:
        exporter = getattr(self.app, "obsidian", None)
        if exporter:
            return exporter.names()
        from .highlights import color_names
        return color_names()

    def push(self):
        """Список выделений — странице книги (она перерисует подсветку)."""
        data = [{k: h.get(k) for k in ("id", "section", "cfi", "text", "prefix", "suffix", "color")}
                for h in self.items()]
        self.reader.js(f"window.reader?.setHighlights({json.dumps(data, ensure_ascii=False)})")

    def _on_changed(self, book_id):
        if book_id == self.book["id"]:
            self.push()
            if self.popover.isVisible():
                self.fill()

    # --- сообщения страницы

    def on_add(self, msg):
        fields = {k: msg.get(k) for k in ("section", "cfi", "text", "prefix", "suffix", "color", "chapter",
                                          "fraction")}
        if not (fields["text"] or "").strip():
            return
        h = self.app.highlights.add(self.book, **fields)
        if msg.get("withNote"):
            self.edit_note(h["id"])

    def on_menu(self, msg):
        h = self.app.highlights.get(self.book, msg.get("id"))
        if not h:
            return
        menu = QMenu(self.reader)
        names = self.names()
        for c in COLORS:
            act = menu.addAction(color_icon(c), names[c])
            act.setCheckable(True)
            act.setChecked(h.get("color") == c)
            act.triggered.connect(lambda _=False, c=c: self.app.highlights.update(self.book, h["id"], color=c))
        menu.addSeparator()
        menu.addAction(tr("Заметка…") if not h.get("note") else tr("Изменить заметку…"),
                       lambda: self.edit_note(h["id"]))
        menu.addAction(tr("Копировать"), lambda: QGuiApplication.clipboard().setText(h.get("text") or ""))
        menu.addSeparator()
        menu.addAction(tr("Удалить выделение"), lambda: self.app.highlights.remove(self.book, h["id"]))
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.popup(QCursor.pos())          # без вложенного цикла событий, как меню книги

    @staticmethod
    def copy(msg):
        QGuiApplication.clipboard().setText(msg.get("text") or "")

    # --- заметка

    def edit_note(self, hid):
        h = self.app.highlights.get(self.book, hid)
        if not h:
            return
        dlg, v = frameless_dialog(self.reader.window(), tr("Заметка"), 460)
        body = QWidget()
        b = QVBoxLayout(body)
        b.setContentsMargins(18, 14, 18, 18)
        b.setSpacing(10)
        quote = QLabel("«" + (h.get("text") or "")[:400] + "»")
        quote.setWordWrap(True)
        cls(quote, "dim")
        b.addWidget(quote)
        edit = QPlainTextEdit(h.get("note") or "")
        edit.setPlaceholderText(tr("Мысль, вопрос, как применить…"))
        edit.setMinimumHeight(140)
        b.addWidget(edit)
        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton(tr("Отмена"))
        save = QPushButton(tr("Сохранить"))
        cls(save, "suggested")
        cancel.clicked.connect(dlg.reject)
        save.clicked.connect(dlg.accept)
        row.addWidget(cancel)
        row.addWidget(save)
        b.addLayout(row)
        v.addWidget(body)
        edit.setFocus()
        if exec_dialog(dlg):
            self.app.highlights.update(self.book, hid, note=edit.toPlainText().strip())

    # --- список в шапке

    def fill(self):
        self.list.clear()
        items = self.items()
        names = self.names()
        for h in items:
            text = (h.get("text") or "").strip().replace("\n", " ")
            line = (text[:220] + "…") if len(text) > 220 else text
            meta = " · ".join(x for x in (names.get(h.get("color"), ""), (h.get("chapter") or "").strip()) if x)
            note = (h.get("note") or "").strip()
            it = QListWidgetItem(color_icon(h.get("color")), f"{line}\n{meta}" + (f"\n✎ {note}" if note else ""))
            it.setData(Qt.ItemDataRole.UserRole, h["id"])
            self.list.addItem(it)
        self.list.setVisible(bool(items))
        self.empty.setVisible(not items)
        exporter = getattr(self.app, "obsidian", None)
        self.obsidian_btn.setVisible(bool(items and exporter and exporter.enabled and exporter.vault()))

    def _on_item(self, item):
        self.go_to(item.data(Qt.ItemDataRole.UserRole))
        self.popover.hide()

    def go_to(self, hid):
        self.reader.js(f"window.reader?.goToHighlight({json.dumps(hid)})")

    def _open_obsidian(self):
        pages = self.app.highlight_pages
        pages.export_book(self.book)            # не ждём таймера — страница должна быть свежей
        uri = pages.open_page(self.book)
        if uri:
            QDesktopServices.openUrl(QUrl(uri))
        self.popover.hide()
