"""Страница «Карта освоения»: что я знаю — темы с уровнем освоения и что делать дальше; копия — в вики."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QProgressBar, QPushButton, QScrollArea, QVBoxLayout,
                               QWidget)

from . import mastery
from .core import log
from .i18n import tr
from .widgets import HeaderBar, IconButton, cls, enable_touch_scroll, label

LEVEL_COLORS = {"none": "#9a9996", "started": "#62a0ea", "learning": "#3584e4", "understand": "#e5a50a",
                "mastered": "#26a269"}
WIKI_PAGE = "wiki/plans/Карта освоения.md"


class MasteryPage(QWidget):
    transient = True            # после ухода со страницы — удалить (App.go_back)

    def __init__(self, app):
        super().__init__()
        self.setObjectName("page")
        self.app = app
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        header = HeaderBar(app.window, tr("Карта освоения"))
        back = IconButton("go-previous", tr("Назад"))
        back.clicked.connect(app.go_back)
        header.pack_start(back)
        lay.addWidget(header)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        body.setMaximumWidth(860)
        self.box = QVBoxLayout(body)
        self.box.setContentsMargins(24, 18, 24, 24)
        self.box.setSpacing(12)
        wrap = QWidget()
        wl = QHBoxLayout(wrap)
        wl.addStretch()
        wl.addWidget(body, 10)
        wl.addStretch()
        scroll.setWidget(wrap)
        enable_touch_scroll(scroll)
        lay.addWidget(scroll, 1)
        self.refresh()

    # --- данные

    def topics(self) -> list:
        return mastery.build(self.app.library, self.app.highlights, self.app.library.stats)

    def refresh(self):
        while self.box.count():
            item = self.box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        topics = self.topics()
        names = mastery.level_names()
        counts = {lv: sum(1 for t in topics if t.level == lv) for lv in mastery.LEVELS}
        self.box.addWidget(label(tr("Что я знаю: темы библиотеки по уровню освоения. Уровень растёт с прочитанными "
                                    "книгами и с тем, что осмыслено в вики."), "dim", wrap=True))
        self.box.addWidget(label(" · ".join(f"{names[lv]}: {counts[lv]}" for lv in reversed(mastery.LEVELS)
                                            if counts[lv]), "caption", wrap=True))
        tips = mastery.attention(topics)
        if tips:
            self.box.addWidget(label(tr("Куда обратить внимание"), "title2"))
            for kind, t in tips[:8]:
                self.box.addWidget(self._tip(kind, t))
        self.box.addWidget(label(tr("Темы"), "title2"))
        for t in topics:
            self.box.addWidget(self._topic_card(t, names))
        self.box.addStretch()
        self.export(topics, tips)

    # --- элементы

    def _tip(self, kind, t) -> QWidget:
        row = QFrame()
        cls(row, "recentcard")
        h = QHBoxLayout(row)
        h.setContentsMargins(12, 8, 12, 8)
        h.addWidget(label(mastery.tip_text(kind, t), "caption", wrap=True), 1)
        if kind in ("continue", "untouched"):
            b = QPushButton(tr("Сделать фокусом"))
            b.clicked.connect(lambda _=False, tt=t: self._make_focus(tt))
            h.addWidget(b)
        elif kind == "questions" and t.question_texts:
            b = QPushButton(tr("К вопросу"))
            book, hl = t.question_texts[0]
            b.clicked.connect(lambda _=False, bid=book["id"], hid=hl["id"]:
                              self.app.open_link(f"muninhall://open?book={bid}&hl={hid}"))
            h.addWidget(b)
        return row

    def _topic_card(self, t, names) -> QWidget:
        card = QFrame()
        cls(card, "recentcard")
        v = QVBoxLayout(card)
        v.setContentsMargins(14, 10, 14, 10)
        v.setSpacing(4)
        top = QHBoxLayout()
        top.addWidget(label(t.name, "heading", wrap=True), 1)
        badge = label(names[t.level], "caption")
        badge.setStyleSheet(f"color: white; background: {LEVEL_COLORS[t.level]}; border-radius: 8px; "
                            "padding: 2px 8px; font-weight: 600;")
        top.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(top)
        bar = QProgressBar()
        bar.setRange(0, max(1, t.total))
        bar.setValue(t.finished)
        bar.setTextVisible(False)
        bar.setFixedHeight(5)
        v.addWidget(bar)
        meta = [tr("прочитано {0} из {1}", t.finished, t.total)]
        if t.reading:
            meta.append(tr("читаю {0}", t.reading))
        if t.seconds:
            meta.append(mastery.hours(t.seconds))
        if t.quotes:
            meta.append(tr("цитат {0}", t.quotes))
        if t.questions:
            meta.append(tr("вопросов {0}", t.questions))
        if t.ingested:
            meta.append(tr("осмыслено в вики {0}", t.ingested))
        v.addWidget(label(" · ".join(meta), "dim", "caption", wrap=True))
        books = QWidget()
        bl = QVBoxLayout(books)
        bl.setContentsMargins(0, 4, 0, 0)
        bl.setSpacing(2)
        marks = {"finished": "✓", "reading": "▶", "unread": "·"}
        order = {"reading": 0, "unread": 1, "finished": 2}
        for b in sorted(t.books, key=lambda b: order[self.app.library.status(b)])[:30]:
            st = self.app.library.status(b)
            btn = QPushButton(f"{marks[st]}  {b.get('title', '')[:70]}")
            cls(btn, "flat")
            btn.setStyleSheet("text-align: left; padding: 2px 6px;")
            btn.clicked.connect(lambda _=False, bid=b["id"]: self.app.on_book_activated(bid))
            bl.addWidget(btn)
        books.hide()
        buttons = QHBoxLayout()
        toggle = QPushButton(tr("Книги темы"))
        toggle.setCheckable(True)
        toggle.toggled.connect(books.setVisible)
        buttons.addWidget(toggle)
        focus = QPushButton(tr("Сделать фокусом"))
        focus.clicked.connect(lambda _=False, tt=t: self._make_focus(tt))
        buttons.addWidget(focus)
        buttons.addStretch()
        v.addLayout(buttons)
        v.addWidget(books)
        return card

    def _make_focus(self, t):
        from .focus import ENOUGH_DEFAULT
        self.app.focus.set_focus(t.name[:1].upper() + t.name[1:], [(t.kind, t.name)], ENOUGH_DEFAULT)
        self.app.on_focus_changed()
        self.app.toast(tr("Фокус: {0}", t.name))

    # --- копия в вики

    def export(self, topics, tips):
        link = self.app.obsidian
        v = link.vault() if link.enabled else None
        if not v:
            return
        from .obsidian import BLOCK_END, BLOCK_START, merge_page
        names = mastery.level_names()
        today = date.today().isoformat()
        lines = [BLOCK_START, tr("<!-- Блок обновляет Muninhall. Свои цели и выводы пишите выше или ниже. -->"), "",
                 "| " + " | ".join((tr("Тема"), tr("Уровень"), tr("Прочитано"), tr("Читаю"), tr("Цитаты"),
                                    tr("Вопросы"), tr("Осмыслено"))) + " |",
                 "|---|---|---|---|---|---|---|"]
        for t in topics:
            lines.append(f"| {t.name} | {names[t.level]} | {t.finished}/{t.total} | {t.reading} | {t.quotes} | "
                         f"{t.questions} | {t.ingested} |")
        if tips:
            lines += ["", f"## {tr('Куда обратить внимание')}"]
            lines += [f"- {mastery.tip_text(kind, t, short=True)}" for kind, t in tips[:10]]
        lines.append(BLOCK_END)
        header = {"type": "mastery", "title": tr("Карта освоения"), "created": today, "updated": today}
        existing = v.read_page(WIKI_PAGE)
        text = merge_page(existing, header, "\n".join(lines))
        if text != existing:
            try:
                v.write_page(WIKI_PAGE, text)
                if existing is None:
                    v.append_log(f"## [{today}] mastery | {header['title']}")
            except OSError as e:
                log("карта освоения не записана:", e)
