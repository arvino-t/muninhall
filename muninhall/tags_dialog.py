"""Окно «Теги» книги: теги её карточки в хранилище Obsidian, с подсказками из тегов всего хранилища.

Теги вводятся через запятую; вложенные — через «/» (`ml/сжатие`), как в Obsidian.
"""
from __future__ import annotations

from PySide6.QtCore import QStringListModel, Qt
from PySide6.QtWidgets import QCompleter, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from .i18n import tr
from .widgets import cls, exec_dialog, frameless_dialog


class TagsEdit(QLineEdit):
    """Строка тегов через запятую; подсказка — для последнего (набираемого) тега."""

    def __init__(self, tags: list[str], known: list[str]):
        super().__init__(", ".join(tags))
        self._completer = QCompleter(QStringListModel(known), self)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._completer.setWidget(self)
        self._completer.activated.connect(self._insert)
        self.textEdited.connect(self._suggest)

    def _current(self) -> str:
        return self.text()[:self.cursorPosition()].split(",")[-1].strip()

    def _suggest(self, _text):
        prefix = self._current()
        if not prefix:
            self._completer.popup().hide()
            return
        self._completer.setCompletionPrefix(prefix)
        self._completer.complete()

    def _insert(self, tag: str):
        head = self.text()[:self.cursorPosition()]
        tail = self.text()[self.cursorPosition():]
        cut = head.rfind(",")
        before = head[:cut + 1] + (" " if cut >= 0 else "")
        text = before + tag + ", "
        self.setText(text + tail.lstrip(", "))
        self.setCursorPosition(len(text))

    def tags(self) -> list[str]:
        return [t.strip() for t in self.text().split(",") if t.strip()]


def show_tags_dialog(app, book) -> bool:
    """True — теги изменены."""
    exporter = app.obsidian
    current = exporter.book_tags(book)
    if current is None:
        app.toast(tr("У книги нет карточки в хранилище Obsidian"))
        return False
    dlg, v = frameless_dialog(app.window, tr("Теги"), 460)
    body = QWidget()
    b = QVBoxLayout(body)
    b.setContentsMargins(18, 14, 18, 18)
    b.setSpacing(10)
    title = QLabel(book.get("title") or "")
    title.setWordWrap(True)
    cls(title, "heading")
    b.addWidget(title)
    edit = TagsEdit(current, exporter.all_tags())
    edit.setPlaceholderText(tr("например: ml/сжатие, проекты/статья"))
    b.addWidget(edit)
    hint = QLabel(tr("Через запятую; вложенные — через «/». Теги пишутся в карточку книги в вики и видны "
                     "в графе Obsidian и в графе приложения."))
    hint.setWordWrap(True)
    cls(hint, "dim", "caption")
    b.addWidget(hint)
    row = QHBoxLayout()
    row.addStretch()
    cancel = QPushButton(tr("Отмена"))
    save = QPushButton(tr("Сохранить"))
    cls(save, "suggested")
    cancel.clicked.connect(dlg.reject)
    save.clicked.connect(dlg.accept)
    edit.returnPressed.connect(lambda: None if edit._completer.popup().isVisible() else dlg.accept())
    row.addWidget(cancel)
    row.addWidget(save)
    b.addLayout(row)
    v.addWidget(body)
    edit.setFocus()
    if not exec_dialog(dlg) or edit.tags() == current:
        return False
    exporter.set_book_tags(book, edit.tags())
    graph = getattr(app, "graph_page", None)
    if graph is not None:
        graph.refresh()
    return True
