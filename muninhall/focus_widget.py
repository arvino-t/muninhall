"""«Сейчас в фокусе» — верх страницы «Фокус»: активные фокусы (до двух) — прогресс, следующая книга,
похожие книги, предложение сменить фокус, когда прочитано достаточно."""
from __future__ import annotations

import html

from PySide6.QtWidgets import QFrame, QHBoxLayout, QProgressBar, QPushButton, QVBoxLayout, QWidget

from .focus import ENOUGH_DEFAULT, MAX_ACTIVE
from .focus_dialog import show_focus_dialog
from .i18n import tr
from .widgets import cls, label


class FocusPanel(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(8)

    def _clear(self, layout=None):
        layout = layout or self.box
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().hide()                 # deleteLater — позже, а перерисовка — сразу
                item.widget().deleteLater()
            elif item.layout():
                self._clear(item.layout())

    @staticmethod
    def _buttons(layout, *specs):
        row = QHBoxLayout()
        row.setSpacing(6)
        for text, slot, suggested in specs:
            b = QPushButton(text)
            if suggested:
                cls(b, "suggested")
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch()
        layout.addLayout(row)

    def _edit(self, **kw):
        show_focus_dialog(self.app, **kw)

    def refresh(self):
        self._clear()
        store = self.app.focus
        self.box.addWidget(label(tr("Сейчас в фокусе"), "title2"))
        actives = store.actives
        if not actives:
            self.box.addWidget(label(tr("Задайте тему, которую сейчас развиваете, — приложение будет подсказывать "
                                        "самые подходящие книги и вовремя предложит сменить фокус. Тему можно "
                                        "выбрать и в карте освоения ниже."), "caption", wrap=True))
            self._buttons(self.box, (tr("Задать фокус"), lambda: self._edit(new=True), True))
            return
        for f in actives:                             # друг под другом: рядом Qt обрезает переносимый текст
            self.box.addWidget(self._focus_block(f))
        view = self.app.library_view
        specs = [(tr("Все книги фокуса") if not view.focus_only else tr("Вся библиотека"), self._toggle_filter, False)]
        if len(actives) < MAX_ACTIVE:
            specs.append((tr("Добавить второй фокус"), lambda: self._edit(new=True), False))
        self._buttons(self.box, *specs)

    def _focus_block(self, f) -> QWidget:
        store = self.app.focus
        card = QFrame()
        cls(card, "recentcard")
        cls(card, "focuscard")
        box = QVBoxLayout(card)
        box.setContentsMargins(14, 10, 14, 10)
        box.setSpacing(5)
        p = store.progress(f)
        box.addWidget(label(f["name"], "heading", wrap=True))
        bar = QProgressBar()
        bar.setRange(0, max(1, p["total"]))
        bar.setValue(p["finished"])
        bar.setTextVisible(False)
        bar.setFixedHeight(5)
        box.addWidget(bar)
        box.addWidget(label(tr("Прочитано {0} из {1} · читаю {2} · порог «достаточно» — {3}",
                               p["finished"], p["total"], p["reading"], f.get("enough", 5)), "dim", "caption",
                            wrap=True))
        if p["enough"]:
            msg = label(tr("Прочитано достаточно, чтобы разобраться в теме. Закрепите прочитанное в вики (конспект, "
                           "понятия) и смените фокус, чтобы не застрять в одной теме."), "caption", wrap=True)
            msg.setStyleSheet("font-weight: 600;")
            box.addWidget(msg)
            topics = store.next_topics(3)
            if topics:
                box.addWidget(label(tr("Следующим фокусом может быть:"), "dim", "caption"))
                for kind, name, n in topics:
                    short = name if len(name) <= 38 else name[:36] + "…"
                    b = QPushButton(f"{short} · {n}")
                    cls(b, "flat")
                    b.setStyleSheet("text-align: left; padding: 3px 8px;")
                    b.setToolTip(tr("Непрочитанных книг: {0}", n))
                    b.clicked.connect(lambda _=False, k=kind, nm=name, old=f["id"]: self._replace(old, k, nm))
                    box.addWidget(b)
        nxt = p["next"]
        if nxt:
            what = tr("Продолжить") if self.app.library.status(nxt) == "reading" else tr("Дальше")
            box.addWidget(label(f"{what}: <b>{html.escape(nxt.get('title', ''))}</b>", "caption", wrap=True,
                                rich=True))
        related = store.related(3, f)
        if related:
            rel = label(tr("Похожие вне фокуса: {0}", ", ".join(html.escape(b.get("title", "")[:40]) for b in related)),
                        "dim", "caption", wrap=True, rich=True)
            rel.setToolTip(tr("Можно добавить в фокус из меню книги"))
            box.addWidget(rel)
        box.addStretch()
        specs = []
        if nxt:
            specs.append((tr("Слушать") if nxt.get("is_audio") else tr("Читать"),
                          lambda _=False, bid=nxt["id"]: self.app.on_book_activated(bid), True))
        specs.append((tr("Изменить"), lambda _=False, fid=f["id"]: self._edit(fid=fid), False))
        self._buttons(box, *specs)
        return card

    def _replace(self, old_fid, kind, name):
        """Сменить фокус на предложенную тему: новый заменяет тот, по которому прочитано достаточно."""
        self.app.focus.set_focus(name[:1].upper() + name[1:], [(kind, name)], ENOUGH_DEFAULT, replace=old_fid)
        self.app.on_focus_changed()
        self._edit(fid=self.app.focus.actives[-1]["id"])   # сразу уточнить теги нового фокуса

    def _toggle_filter(self):
        """Оставить в библиотеке только книги фокуса (или вернуть все) — и показать библиотеку."""
        view = self.app.library_view
        view.set_focus_only(not view.focus_only)
        self.app.pop_to_library()
