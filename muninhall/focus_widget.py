"""Раздел «Фокус на развитии» в правой панели библиотеки: тема, прогресс, следующая книга, похожие книги,
предложение сменить фокус, когда прочитано достаточно."""
from __future__ import annotations

import html

from PySide6.QtWidgets import QFrame, QHBoxLayout, QProgressBar, QPushButton, QVBoxLayout, QWidget

from .focus_dialog import show_focus_dialog
from .i18n import tr
from .widgets import cls, label


class FocusPanel(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(10)
        lay.addWidget(label(tr("Фокус на развитии"), "title2"))
        self.card = QFrame()
        cls(self.card, "recentcard")
        self.box = QVBoxLayout(self.card)
        self.box.setContentsMargins(14, 12, 14, 12)
        self.box.setSpacing(6)
        lay.addWidget(self.card)
        self._next = None

    def _clear(self):
        while self.box.count():
            item = self.box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                lay = item.layout()
                while lay.count():
                    w = lay.takeAt(0).widget()
                    if w:
                        w.deleteLater()

    def _buttons(self, *specs):
        row = QHBoxLayout()
        row.setSpacing(6)
        for text, slot, suggested in specs:
            b = QPushButton(text)
            if suggested:
                cls(b, "suggested")
            b.clicked.connect(slot)
            row.addWidget(b)
        self.box.addLayout(row)

    def refresh(self):
        self._clear()
        store = self.app.focus
        f = store.active
        view = self.app.library_view
        if not f:
            self.box.addWidget(label(tr("Задайте тему, которую сейчас развиваете, — приложение будет подсказывать "
                                        "самые подходящие книги и вовремя предложит сменить фокус."), "caption",
                                     wrap=True))
            self._buttons((tr("Задать фокус"), lambda: show_focus_dialog(self.app), True))
            return
        p = store.progress(f)
        self.box.addWidget(label(f["name"], "heading", wrap=True))
        bar = QProgressBar()
        bar.setRange(0, max(1, p["total"]))
        bar.setValue(p["finished"])
        bar.setTextVisible(False)
        bar.setFixedHeight(5)
        self.box.addWidget(bar)
        self.box.addWidget(label(tr("Прочитано {0} из {1} · читаю {2} · порог «достаточно» — {3}",
                                    p["finished"], p["total"], p["reading"], f.get("enough", 5)), "dim", "caption",
                                 wrap=True))
        self._next = p["next"]
        if p["enough"]:
            msg = label(tr("Прочитано достаточно, чтобы разобраться в теме. Закрепите прочитанное в вики (конспект, "
                           "понятия) и смените фокус, чтобы не застрять в одной теме."), "caption", wrap=True)
            msg.setStyleSheet("font-weight: 600;")
            self.box.addWidget(msg)
            topics = store.next_topics(3)
            if topics:
                self.box.addWidget(label(tr("Следующим фокусом может быть:"), "dim", "caption"))
                for kind, name, n in topics:          # столбиком: длинные названия тем в ряд не помещаются
                    short = name if len(name) <= 38 else name[:36] + "…"
                    b = QPushButton(f"{short} · {n}")
                    cls(b, "flat")
                    b.setStyleSheet("text-align: left; padding: 3px 8px;")
                    b.setToolTip(tr("Непрочитанных книг: {0}", n))
                    b.clicked.connect(lambda _=False, k=kind, nm=name: show_focus_dialog(
                        self.app, preset=(nm[:1].upper() + nm[1:], [(k, nm)])))
                    self.box.addWidget(b)
        if self._next:
            nb = self._next
            what = tr("Продолжить") if self.app.library.status(nb) == "reading" else tr("Дальше")
            self.box.addWidget(label(f"{what}: <b>{html.escape(nb.get('title', ''))}</b>", "caption", wrap=True,
                                     rich=True))
        related = store.related(3)
        if related:
            rel = label(tr("Похожие вне фокуса: {0}", ", ".join(html.escape(b.get("title", "")[:40]) for b in related)),
                        "dim", "caption", wrap=True, rich=True)
            rel.setToolTip(tr("Можно добавить в фокус из меню книги"))
            self.box.addWidget(rel)
        only = view.focus_only
        if self._next:                               # кнопки в два ряда — в одну строку не помещаются
            self._buttons((tr("Слушать") if self._next.get("is_audio") else tr("Читать"),
                           lambda: self.app.on_book_activated(self._next["id"]), True))
        self._buttons((tr("Все книги фокуса") if not only else tr("Вся библиотека"), self._toggle_filter, False),
                      (tr("Изменить"), lambda: show_focus_dialog(self.app), False))

    def _toggle_filter(self):
        view = self.app.library_view
        view.set_focus_only(not view.focus_only)
        self.refresh()
