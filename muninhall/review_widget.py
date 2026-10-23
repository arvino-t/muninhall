"""Раздел «Просмотр дня» в правой панели библиотеки: моя цитата и случайный отрывок из книги."""
from __future__ import annotations

import html
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from .highlights import color_names
from .i18n import tr
from .reader_highlights import RGB
from .widgets import cls, label


def display_text(text: str, limit: int = 0) -> str:
    """Для показа: без мягких переносов и с переносами слов из PDF («consis‐ tent» → «consistent»);
    limit — обрезать на границе предложения (целиком отрывок виден в книге)."""
    text = re.sub(r"(\w)[‐-] (\w)", r"\1\2", (text or "").replace("\xad", "")).strip()
    if limit and len(text) > limit:
        cut = max(text.rfind(m, 0, limit) for m in (". ", "! ", "? ", "… "))
        text = text[:cut + 1] if cut > limit // 2 else text[:limit].rsplit(" ", 1)[0] + "…"
    return text


class _Card(QFrame):
    def __init__(self, caption: str):
        super().__init__()
        cls(self, "recentcard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)
        self.caption = label(caption, "dim", "caption", wrap=True)
        self.caption.setTextFormat(Qt.TextFormat.RichText)
        self.quote = label("", wrap=True)
        self.quote.setStyleSheet("font-style: italic;")
        self.note = label("", "caption", wrap=True)
        self.status = label("", "dim", "caption", wrap=True)
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(6)
        for w in (self.caption, self.quote, self.note, self.status):
            lay.addWidget(w)
        lay.addLayout(self.buttons)

    def button(self, text, slot, suggested=False) -> QPushButton:
        b = QPushButton(text)
        if suggested:
            cls(b, "suggested")
        b.clicked.connect(slot)
        self.buttons.addWidget(b)
        return b


class ReviewPanel(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(10)
        lay.addWidget(label(tr("Просмотр дня"), "title2"))
        self.mine_card = _Card(tr("Моя цитата"))
        self.remember_btn = self.mine_card.button(tr("Помню"), lambda: self._answer(True), suggested=True)
        self.later_btn = self.mine_card.button(tr("Позже"), lambda: self._answer(False))
        self.mine_card.button(tr("В книге"), self._open_mine)
        self.random_card = _Card(tr("Из книги"))
        self.save_btn = self.random_card.button(tr("Сохранить цитату"), self._save_random)
        self.random_card.button(tr("В книге"), self._open_random)
        lay.addWidget(self.mine_card)
        lay.addWidget(self.random_card)
        self._mine = None
        self._random = None

    # --- данные

    def refresh(self, with_random=True) -> bool:
        """Заполнить карточки; True — есть что показать."""
        review = self.app.review
        self._mine = review.mine()
        if self._mine:
            book, h = self._mine
            name = color_names().get(h.get("color"), "")
            custom = (self.app.settings.get("highlightColors") or {}).get(h.get("color"))
            r, g, b = RGB.get(h.get("color"), RGB["important"])
            self.mine_card.caption.setText(f"<span style='color: rgb({r},{g},{b})'>●</span> "
                                           f"{html.escape(custom or name)} · {html.escape(book.get('title', ''))}")
            self.mine_card.quote.setText("«" + display_text(h.get("text"), 320) + "»")
            note = (h.get("note") or "").strip()
            self.mine_card.note.setText(f"✎ {note}" if note else "")
            self.mine_card.note.setVisible(bool(note))
            done = review.data.get("mine", {}).get("done")
            st = review.data["srs"].get(h["id"], {})
            self.mine_card.status.setText(
                tr("Следующий раз через {0} дн.", st.get("interval", 1)) if done else "")
            self.mine_card.status.setVisible(bool(done))
            self.remember_btn.setVisible(not done)
            self.later_btn.setVisible(not done)
        else:
            self.mine_card.caption.setText(html.escape(tr("Моя цитата")))
            self.mine_card.quote.setText(tr("Выделяйте важное в книгах — цитаты будут возвращаться сюда, "
                                            "чтобы не забывались."))
            self.mine_card.note.hide()
            self.mine_card.status.hide()
        for b in (self.remember_btn, self.later_btn):
            b.setEnabled(bool(self._mine))
        if with_random:
            self._random = review.random_passage()
        if self._random:
            book, r = self._random
            self.random_card.caption.setText(html.escape(tr("Из книги «{0}»", book.get("title", ""))))
            self.random_card.quote.setText("«" + display_text(r["text"], 260) + "»")
            saved = bool(r.get("hid"))
            self.save_btn.setEnabled(not saved)
            self.save_btn.setText(tr("Сохранено") if saved else tr("Сохранить цитату"))
            self.random_card.note.hide()
            self.random_card.status.hide()
        self.random_card.setVisible(bool(self._random))
        return bool(self._mine or self._random)

    # --- действия

    def _answer(self, remembered: bool):
        if self._mine:
            self.app.review.answer(self._mine[1]["id"], remembered)
            self.refresh(with_random=False)

    def _open_mine(self):
        if self._mine:
            book, h = self._mine
            self.app.open_link(f"muninhall://open?book={book['id']}&hl={h['id']}")

    def _save_random(self):
        h = self.app.review.save_random()
        if h:
            self.app.toast(tr("Цитата сохранена в выделения книги"))
            self.refresh(with_random=False)

    def _open_random(self):
        if not self._random:
            return
        book, r = self._random
        h = self.app.review.save_random() if r.get("hid") else None
        if h:
            self.app.open_link(f"muninhall://open?book={book['id']}&hl={h['id']}")
            return
        self.app.on_book_activated(book["id"])
        if self.app.reader and self.app.reader.book["id"] == book["id"]:
            self.app.reader.go_to_quote({k: r[k] for k in ("section", "text", "prefix", "suffix")})
